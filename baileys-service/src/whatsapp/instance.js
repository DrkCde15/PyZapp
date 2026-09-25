'use strict';

const {
  default: makeWASocket,
  DisconnectReason,
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
const MAX_RECONNECT_DELAY_MS = 30_000;
const WEBHOOK_META_FILE = 'webhook.json';

/**
 * One WhatsApp connection. Owns a single Baileys socket and its
 * connection state machine:
 *
 *   created -> connecting -> qr_pending -> connected
 *                                  \-> disconnected -> connecting (retry)
 *                                  \-> logged_out (needs fresh connect)
 */
class WhatsAppInstance {
  constructor({ id, sessionStore, socketFactory, logger }) {
    this.id = id;
    this.sessionStore = sessionStore;
    this.socketFactory = socketFactory || ((opts) => makeWASocket(opts));
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
   * Normalize inbound Baileys messages to plain-text events.
   * MVP scope: 1:1 text chats only (no groups, status, newsletters, media).
   */
  _onInboundMessages(messages) {
    for (const msg of messages) {
      try {
        const payload = this._toInboundPayload(msg);
        if (!payload) continue;
        this.log.info(
          { event: 'message_received', from: maskPhone(payload.from), message_id: payload.message_id },
          'Inbound message'
        );
        this.onInbound?.(payload);
      } catch (err) {
        this.log.error({ event: 'inbound_parse_failed', error: err.message }, 'Failed to parse inbound');
      }
    }
  }

  _toInboundPayload(msg) {
    const key = msg?.key || {};
    if (key.fromMe) return null;
    const remoteJid = key.remoteJid || '';
    // Skip groups, status broadcasts and newsletters in this MVP.
    if (remoteJid.endsWith('@g.us') || remoteJid.endsWith('@broadcast') || remoteJid.endsWith('@newsletter')) {
      return null;
    }
    const text = msg?.message?.conversation || msg?.message?.extendedTextMessage?.text;
    if (typeof text !== 'string' || !text.trim()) return null;
    return {
      event: 'message.received',
      instance_id: this.id,
      message_id: key.id || null,
      from: remoteJid.split('@')[0],
      text,
      timestamp: Number(msg.messageTimestamp) || null,
    };
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

module.exports = { WhatsAppInstance };
