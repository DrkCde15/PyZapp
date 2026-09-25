'use strict';

const {
  default: makeWASocket,
  DisconnectReason,
  downloadMediaMessage,
} = require('@whiskeysockets/baileys');
const {
  InstanceNotConnectedError,
  QrNotAvailableError,
  BaileysOperationError,
  ConnectionNotReadyError,
  InvalidInputError,
  normalizePhone,
  toJid,
} = require('../errors');
const { withInstance, maskPhone } = require('../logger');

const MAX_TEXT_LENGTH = 4096;
const MAX_CAPTION_LENGTH = 1024;
const MAX_RECONNECT_DELAY_MS = 30_000;
const WEBHOOK_META_FILE = 'webhook.json';
// WhatsApp caps media around 16MB; stay below with headroom.
const MAX_MEDIA_BYTES = 12 * 1024 * 1024;

const MEDIA_TYPES = ['image', 'audio', 'document'];
const IMAGE_MIMES = ['image/jpeg', 'image/png', 'image/webp'];
const AUDIO_MIMES = ['audio/ogg; codecs=opus', 'audio/mp4', 'audio/mpeg'];

/**
 * One WhatsApp connection. Owns a single Baileys socket and its
 * connection state machine:
 *
 *   created -> connecting -> qr_pending -> connected
 *                                  \-> disconnected -> connecting (retry)
 *                                  \-> logged_out (needs fresh connect)
 */
class WhatsAppInstance {
  constructor({ id, sessionStore, socketFactory, mediaDownloader, logger }) {
    this.id = id;
    this.sessionStore = sessionStore;
    this.socketFactory = socketFactory || ((opts) => makeWASocket(opts));
    this.mediaDownloader =
      mediaDownloader || ((msg) => downloadMediaMessage(msg, 'buffer', {}));
    this.log = logger || withInstance(id);

    this.status = 'created';
    this.sock = null;
    this.lastQr = null;
    this.qrUpdatedAt = null;
    this.phone = null;
    this.updatedAt = new Date().toISOString();
    this.reconnectDelayMs = 1000;
    this.reconnectTimer = null;
    this.destroyed = false;
    // Outbound handler wired by WhatsAppManager: (payload) => void.
    this.onInbound = null;
    this.webhook = null;
  }

  touch(status) {
    this.status = status;
    this.updatedAt = new Date().toISOString();
  }

  /** Start (or restart) the Baileys socket. Idempotent when connected. */
  async connect() {
    if (this.destroyed) {
      throw new BaileysOperationError(`Instance '${this.id}' was destroyed`);
    }
    if (this.status === 'connected' && this.sock) return this.snapshot();
    if (this.sock && (this.status === 'connecting' || this.status === 'qr_pending')) {
      return this.snapshot();
    }

    // A logged-out session can never resume: wipe it so a fresh QR is issued.
    if (this.status === 'logged_out') {
      this.log.info({ event: 'session_reset' }, 'Clearing logged-out session');
      await this.sessionStore.clear(this.id);
      this._closeSocket();
    }

    this.touch('connecting');
    this.log.info({ event: 'connecting' }, 'Opening Baileys socket');

    const { state, saveCreds } = await this.sessionStore.load(this.id);
    const sock = this.socketFactory({
      auth: state,
      printQRInTerminal: false,
      markOnlineOnConnect: false,
      syncFullHistory: false,
      browser: ['PyZapp', 'Chrome', '122.0.0.0'],
    });
    this.sock = sock;

    sock.ev.on('creds.update', saveCreds);
    sock.ev.on('connection.update', (update) => {
      this._onConnectionUpdate(update).catch((err) => {
        this.log.error({ event: 'connection_update_failed', error: err.message }, 'Failed to handle update');
      });
    });
    sock.ev.on('messages.upsert', ({ messages, type }) => {
      if (type === 'notify') this._onInboundMessages(messages || []);
    });

    return this.snapshot();
  }

  async _onConnectionUpdate(update) {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      this.lastQr = qr;
      this.qrUpdatedAt = new Date().toISOString();
      this.touch('qr_pending');
      this.log.info({ event: 'qr_received' }, 'QR code available for scan');
    }

    if (connection === 'open') {
      this.lastQr = null;
      this.reconnectDelayMs = 1000;
      this.phone = this._extractPhone();
      this.touch('connected');
      this.log.info({ event: 'connected', phone: maskPhone(this.phone) }, 'WhatsApp connected');
    }

    if (connection === 'close') {
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const reasonName =
        Object.keys(DisconnectReason).find((k) => DisconnectReason[k] === statusCode) || 'unknown';
      this.log.warn({ event: 'disconnected', status_code: statusCode, reason: reasonName }, 'Connection closed');

      if (statusCode === DisconnectReason.loggedOut) {
        this._closeSocket();
        this.touch('logged_out');
        this.log.warn({ event: 'logged_out' }, 'Logged out: session must be recreated');
        return;
      }
      // WhatsApp forces a reconnect right after QR scan to present credentials.
      this._closeSocket();
      this.touch('disconnected');
      this._scheduleReconnect();
    }
  }

  _extractPhone() {
    try {
      const raw = this.sock?.user?.id || '';
      return raw.split(':')[0].split('@')[0] || null;
    } catch {
      return null;
    }
  }

  _scheduleReconnect() {
    if (this.destroyed) return;
    clearTimeout(this.reconnectTimer);
    const delay = this.reconnectDelayMs;
    this.reconnectDelayMs = Math.min(delay * 2, MAX_RECONNECT_DELAY_MS);
    this.log.info({ event: 'reconnect_scheduled', delay_ms: delay }, 'Reconnecting');
    this.reconnectTimer = setTimeout(() => {
      if (!this.destroyed && this.status !== 'connected') {
        this.connect().catch((err) => {
          this.log.error({ event: 'reconnect_failed', error: err.message }, 'Reconnect attempt failed');
          this._scheduleReconnect();
        });
      }
    }, delay);
    this.reconnectTimer.unref?.();
  }

  _closeSocket() {
    clearTimeout(this.reconnectTimer);
    const sock = this.sock;
    this.sock = null;
    if (sock) {
      try {
        sock.ev.removeAllListeners('connection.update');
        sock.ev.removeAllListeners('creds.update');
        sock.ev.removeAllListeners('messages.upsert');
        sock.end?.();
      } catch {
        // best effort
      }
    }
  }

  /** Send a plain-text message. Requires an active connection. */
  async sendText(to, text) {
    if (typeof text !== 'string' || text.trim().length === 0) {
      throw new InvalidInputError('Message text must be a non-empty string');
    }
    if (text.length > MAX_TEXT_LENGTH) {
      throw new InvalidInputError(`Message text exceeds ${MAX_TEXT_LENGTH} characters`);
    }
    if (this.status !== 'connected' || !this.sock) {
      throw new InstanceNotConnectedError(this.id);
    }
    const jid = toJid(to);
    try {
      const sent = await this.sock.sendMessage(jid, { text });
      const messageId = sent?.key?.id;
      this.log.info({ event: 'message_sent', to: maskPhone(to), message_id: messageId }, 'Message sent');
      return messageId;
    } catch (err) {
      this.log.error({ event: 'message_failed', to: maskPhone(to), error: err.message }, 'Send failed');
      throw new BaileysOperationError(`Failed to send message: ${err.message}`);
    }
  }

  /**
   * Send media: image | audio | document.
   * `dataBase64` is the raw file encoded in base64 (validated + capped).
   * Options: { mimetype, caption (image/document), filename (document),
   *            voiceNote (audio: send as voice message) }.
   */
  async sendMedia(to, mediaType, dataBase64, options = {}) {
    if (!MEDIA_TYPES.includes(mediaType)) {
      throw new InvalidInputError(`media_type must be one of: ${MEDIA_TYPES.join(', ')}`);
    }
    if (this.status !== 'connected' || !this.sock) {
      throw new InstanceNotConnectedError(this.id);
    }
    const buffer = decodeMedia(dataBase64);
    const { mimetype, caption = '', filename = null, voiceNote = false } = options;
    if (caption.length > MAX_CAPTION_LENGTH) {
      throw new InvalidInputError(`Caption exceeds ${MAX_CAPTION_LENGTH} characters`);
    }
    const content = buildMediaContent(mediaType, buffer, { mimetype, caption, filename, voiceNote });
    const jid = toJid(to);
    try {
      const sent = await this.sock.sendMessage(jid, content);
      const messageId = sent?.key?.id;
      this.log.info(
        { event: 'media_sent', to: maskPhone(to), media_type: mediaType, message_id: messageId },
        'Media sent'
      );
      return messageId;
    } catch (err) {
      this.log.error(
        { event: 'media_failed', to: maskPhone(to), media_type: mediaType, error: err.message },
        'Send media failed'
      );
      throw new BaileysOperationError(`Failed to send media: ${err.message}`);
    }
  }

  getQr() {
    if (!this.lastQr || this.status !== 'qr_pending') {
      throw new QrNotAvailableError(this.id, this.status);
    }
    return { qr: this.lastQr, updated_at: this.qrUpdatedAt };
  }

  /**
   * Alternative to QR scan: user types the returned code on their phone
   * (WhatsApp > Linked devices > Link with phone number).
   */
  async requestPairingCode(phone) {
    const digits = normalizePhone(phone);
    if (!this.sock) await this.connect();
    if (this.status === 'connected') {
      throw new InvalidInputError(`Instance '${this.id}' is already connected`);
    }
    await this._waitForSocketOpen();
    try {
      const code = await this.sock.requestPairingCode(digits);
      this.log.info({ event: 'pairing_code_issued', to: maskPhone(digits) }, 'Pairing code issued');
      return code;
    } catch (err) {
      this.log.error({ event: 'pairing_code_failed', to: maskPhone(digits), error: err.message }, 'Pairing failed');
      throw new BaileysOperationError(`Failed to issue pairing code: ${err.message}`);
    }
  }

  /**
   * The pairing-code stanza requires an open WebSocket. Poll briefly
   * instead of failing on a socket that is still handshaking.
   */
  async _waitForSocketOpen(timeoutMs = 15000, intervalMs = 200) {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const ws = this.sock?.ws;
      if (!ws || ws.isOpen) return; // absent ws = test double: assume open
      if (Date.now() > deadline) throw new ConnectionNotReadyError(this.id);
      await new Promise((r) => setTimeout(r, intervalMs));
    }
  }

  /** Configure where inbound messages are delivered. Persists across restarts. */
  async setWebhook(url, secret = null) {
    let parsed;
    try {
      parsed = new URL(url);
    } catch {
      throw new InvalidInputError('Webhook url must be a valid absolute URL');
    }
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      throw new InvalidInputError('Webhook url must use http(s)');
    }
    this.webhook = { url: parsed.toString(), secret };
    await this.sessionStore.writeMeta(this.id, WEBHOOK_META_FILE, this.webhook);
    this.log.info({ event: 'webhook_configured' }, 'Webhook configured');
    return this.webhook;
  }

  async loadWebhook() {
    const saved = await this.sessionStore.readMeta(this.id, WEBHOOK_META_FILE);
    if (saved?.url) this.webhook = saved;
    return this.webhook;
  }

  /**
   * Normalize inbound Baileys messages.
   * Scope: 1:1 chats, text + image/audio/document (groups, status,
   * newsletters still skipped). Media arrives as base64 under a size cap.
   */
  _onInboundMessages(messages) {
    for (const msg of messages) {
      this._toInboundPayload(msg)
        .then((payload) => {
          if (!payload) return;
          this.log.info(
            {
              event: 'message_received',
              from: maskPhone(payload.from),
              message_id: payload.message_id,
              media_type: payload.media?.type || null,
            },
            'Inbound message'
          );
          this.onInbound?.(payload);
        })
        .catch((err) => {
          this.log.error({ event: 'inbound_parse_failed', error: err.message }, 'Failed to parse inbound');
        });
    }
  }

  async _toInboundPayload(msg) {
    const key = msg?.key || {};
    if (key.fromMe) return null;
    const remoteJid = key.remoteJid || '';
    // Skip groups, status broadcasts and newsletters.
    if (remoteJid.endsWith('@g.us') || remoteJid.endsWith('@broadcast') || remoteJid.endsWith('@newsletter')) {
      return null;
    }
    const base = {
      event: 'message.received',
      instance_id: this.id,
      message_id: key.id || null,
      from: remoteJid.split('@')[0],
      timestamp: Number(msg.messageTimestamp) || null,
    };
    const text = msg?.message?.conversation || msg?.message?.extendedTextMessage?.text;
    if (typeof text === 'string' && text.trim()) {
      return { ...base, text };
    }
    const media = await this._extractInboundMedia(msg);
    if (!media) return null;
    return { ...base, text: media.caption || '', media };
  }

  /** Download inbound media; null when absent, unsupported or over the cap. */
  async _extractInboundMedia(msg) {
    const m = msg?.message || {};
    const found =
      (m.imageMessage && { type: 'image', node: m.imageMessage, caption: m.imageMessage.caption }) ||
      (m.audioMessage && { type: 'audio', node: m.audioMessage, caption: '' }) ||
      (m.documentMessage && {
        type: 'document',
        node: m.documentMessage,
        caption: m.documentMessage.caption || m.documentMessage.title || '',
      });
    if (!found) return null;
    try {
      const buffer = await this.mediaDownloader(msg);
      if (!buffer || buffer.length > MAX_MEDIA_BYTES) {
        this.log.warn(
          { event: 'inbound_media_skipped', media_type: found.type, bytes: buffer?.length || 0 },
          'Inbound media skipped (missing or too large)'
        );
        return null;
      }
      return {
        type: found.type,
        mimetype: found.node.mimetype || null,
        filename: found.node.fileName || null,
        caption: found.caption || '',
        data: buffer.toString('base64'),
      };
    } catch (err) {
      this.log.error({ event: 'inbound_media_failed', media_type: found.type, error: err.message }, 'Media download failed');
      return null;
    }
  }

  /** Destroy the socket. `clearSession=true` also wipes persisted auth. */
  async destroy({ clearSession = false } = {}) {
    this.destroyed = true;
    this._closeSocket();
    if (clearSession) {
      await this.sessionStore.clear(this.id);
      this.log.info({ event: 'session_cleared' }, 'Session wiped');
    }
    this.log.info({ event: 'destroyed' }, 'Instance destroyed');
  }

  snapshot() {
    return {
      instance_id: this.id,
      status: this.status,
      connected: this.status === 'connected',
      phone: this.phone,
      qr_available: this.status === 'qr_pending' && !!this.lastQr,
      webhook_configured: !!this.webhook,
      updated_at: this.updatedAt,
    };
  }
}

module.exports = { WhatsAppInstance, decodeMedia, buildMediaContent };

/** Decode + cap a base64 media payload. Throws InvalidInputError. */
function decodeMedia(dataBase64) {
  if (typeof dataBase64 !== 'string' || !dataBase64.trim()) {
    throw new InvalidInputError('Media data must be a non-empty base64 string');
  }
  let buffer;
  try {
    buffer = Buffer.from(dataBase64, 'base64');
  } catch {
    throw new InvalidInputError('Media data is not valid base64');
  }
  if (buffer.length === 0 || buffer.length > MAX_MEDIA_BYTES) {
    throw new InvalidInputError(
      `Media must be 1 byte–${MAX_MEDIA_BYTES / 1024 / 1024}MB after decoding`
    );
  }
  return buffer;
}

/** Map (type, buffer, options) to a Baileys sendMessage content object. */
function buildMediaContent(mediaType, buffer, { mimetype, caption = '', filename = null, voiceNote = false }) {
  if (mediaType === 'image') {
    if (!IMAGE_MIMES.includes(mimetype)) {
      throw new InvalidInputError(`image mimetype must be one of: ${IMAGE_MIMES.join(', ')}`);
    }
    return { image: buffer, mimetype, caption };
  }
  if (mediaType === 'audio') {
    if (!AUDIO_MIMES.includes(mimetype)) {
      throw new InvalidInputError(`audio mimetype must be one of: ${AUDIO_MIMES.join(', ')}`);
    }
    // ptt=true renders as a voice message instead of an audio file.
    return { audio: buffer, mimetype, ptt: !!voiceNote };
  }
  // document: any mimetype, filename required for a sane download name.
  if (typeof mimetype !== 'string' || !mimetype.includes('/')) {
    throw new InvalidInputError('document mimetype is required, e.g. application/pdf');
  }
  if (typeof filename !== 'string' || !filename.trim()) {
    throw new InvalidInputError('document filename is required');
  }
  return { document: buffer, mimetype, fileName: filename, caption };
}
