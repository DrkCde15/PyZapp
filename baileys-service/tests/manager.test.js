'use strict';

const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs/promises');
const http = require('http');
const os = require('os');
const path = require('path');
const { EventEmitter } = require('events');

const { WhatsAppManager, defaultDeliverWebhook } = require('../src/whatsapp/manager');
const { SessionStore } = require('../src/whatsapp/session');
const {
  InstanceNotFoundError,
  InstanceExistsError,
  InstanceNotConnectedError,
  QrNotAvailableError,
  InvalidInputError,
} = require('../src/errors');

/** Minimal Baileys socket double: real ev emitter, stubbed send/end. */
function makeFakeSocket({ user = null } = {}) {
  const ev = new EventEmitter();
  ev.removeAllListeners = EventEmitter.prototype.removeAllListeners.bind(ev);
  return {
    ev,
    user,
    sent: [],
    ended: false,
    async sendMessage(jid, content) {
      this.sent.push({ jid, content });
      return { key: { id: 'MSGID123' } };
    },
    async requestPairingCode(phone) {
      if (!/^\d{8,15}$/.test(phone)) throw new Error('bad phone');
      return 'ABCD-1234';
    },
    end() {
      this.ended = true;
    },
  };
}

function makeHarness() {
  const sockets = [];
  const socketFactory = () => {
    const sock = makeFakeSocket();
    sockets.push(sock);
    return sock;
  };
  // In-memory session store: no disk, no Baileys auth code in tests.
  const sessions = new Map();
  const metas = new Map();
  const sessionStore = {
    async load(id) {
      if (!sessions.has(id)) sessions.set(id, { saved: 0 });
      return { state: {}, saveCreds: async () => {} };
    },
    async clear(id) {
      sessions.delete(id);
    },
    async exists(id) {
      return sessions.has(id);
    },
    async listIds() {
      return [...sessions.keys()];
    },
    async writeMeta(id, name, obj) {
      metas.set(`${id}/${name}`, obj);
    },
    async readMeta(id, name) {
      return metas.get(`${id}/${name}`) || null;
    },
  };
  const silent = { info() {}, warn() {}, error() {}, child() { return silent; } };
  const manager = new WhatsAppManager({ sessionStore, socketFactory, log: silent });
  return { manager, sockets, sessionStore };
}

describe('WhatsAppManager', () => {
  let manager;
  let sockets;
  beforeEach(() => {
    ({ manager, sockets } = makeHarness());
  });

  it('creates an instance and starts connecting', async () => {
    const snap = await manager.create('inst-1');
    assert.equal(snap.instance_id, 'inst-1');
    assert.equal(snap.status, 'connecting');
    assert.equal(sockets.length, 1);
  });

  it('rejects duplicate and invalid ids', async () => {
    await manager.create('dup');
    await assert.rejects(() => manager.create('dup'), InstanceExistsError);
    await assert.rejects(() => manager.create('bad id!'), InvalidInputError);
    await assert.rejects(() => manager.create(''), InvalidInputError);
  });

  it('lists and gets instances; unknown id raises not found', async () => {
    await manager.create('a');
    await manager.create('b');
    assert.equal(manager.list().length, 2);
    assert.equal(manager.get('a').snapshot().instance_id, 'a');
    assert.throws(() => manager.get('nope'), InstanceNotFoundError);
  });

  it('tracks qr -> connected transitions from connection.update', async () => {
    await manager.create('qr1');
    const sock = sockets[0];
    sock.ev.emit('connection.update', { qr: 'QR-PAYLOAD' });
    assert.equal(manager.get('qr1').snapshot().status, 'qr_pending');
    assert.equal(manager.get('qr1').getQr().qr, 'QR-PAYLOAD');

    sock.user = { id: '5511999999999:12@s.whatsapp.net' };
    sock.ev.emit('connection.update', { connection: 'open' });
    const snap = manager.get('qr1').snapshot();
    assert.equal(snap.status, 'connected');
    assert.equal(snap.phone, '5511999999999');
    assert.throws(() => manager.get('qr1').getQr(), QrNotAvailableError);
  });

  it('marks logged_out on 401 and requires fresh session on reconnect', async () => {
    const h = makeHarness();
    await h.manager.create('gone');
    const sock = h.sockets[0];
    const loggedOut = new Error('logged out');
    loggedOut.output = { statusCode: 401 };
    sock.ev.emit('connection.update', { connection: 'close', lastDisconnect: { error: loggedOut } });
    assert.equal(h.manager.get('gone').snapshot().status, 'logged_out');
    assert.equal(sock.ended, true);
    await h.manager.connect('gone'); // fresh session -> new socket attempt
    assert.equal(h.sockets.length, 2);
  });

  it('sends text only when connected', async () => {
    await manager.create('sender');
    await assert.rejects(() => manager.get('sender').sendText('5511999999999', 'hi'), InstanceNotConnectedError);
    const sock = sockets[0];
    sock.user = { id: '5511000000000:1@s.whatsapp.net' };
    sock.ev.emit('connection.update', { connection: 'open' });
    const id = await manager.get('sender').sendText('+55 11 99999-9999', 'hello');
    assert.equal(id, 'MSGID123');
    assert.equal(sock.sent[0].jid, '5511999999999@s.whatsapp.net');
    await assert.rejects(() => manager.get('sender').sendText('abc', 'hi'), InvalidInputError);
    await assert.rejects(() => manager.get('sender').sendText('5511999999999', '  '), InvalidInputError);
  });

  it('deletes instance and clears session', async () => {
    const h = makeHarness();
    await h.manager.create('bye');
    await h.manager.delete('bye');
    assert.equal(h.manager.count(), 0);
    assert.equal(await h.sessionStore.exists('bye'), false);
    assert.throws(() => h.manager.get('bye'), InstanceNotFoundError);
    await assert.rejects(() => h.manager.delete('bye'), InstanceNotFoundError);
  });

  it('issues a pairing code for a valid phone', async () => {
    await manager.create('pair');
    const code = await manager.requestPairingCode('pair', '+5511999999999');
    assert.equal(code, 'ABCD-1234');
    await assert.rejects(() => manager.requestPairingCode('pair', 'abc'), InvalidInputError);
    await assert.rejects(() => manager.requestPairingCode('missing', '+5511999999999'), InstanceNotFoundError);
  });

  it('refuses pairing code when already connected', async () => {
    await manager.create('linked');
    sockets[0].user = { id: '5511000000000:1@s.whatsapp.net' };
    sockets[0].ev.emit('connection.update', { connection: 'open' });
    await assert.rejects(() => manager.requestPairingCode('linked', '+5511999999999'), InvalidInputError);
  });

  it('configures webhook and validates url', async () => {
    await manager.create('hook');
    const saved = await manager.setWebhook('hook', 'https://example.com/wa', 's3cret');
    assert.equal(saved.url, 'https://example.com/wa');
    assert.equal(manager.get('hook').snapshot().webhook_configured, true);
    await assert.rejects(() => manager.setWebhook('hook', 'ftp://x'), InvalidInputError);
    await assert.rejects(() => manager.setWebhook('hook', 'not-a-url'), InvalidInputError);
  });

  it('delivers inbound text messages to the webhook', async () => {
    const delivered = [];
    const h = makeHarness();
    h.manager.deliverWebhook = async (args) => {
      delivered.push(args);
    };
    await h.manager.create('inbox');
    await h.manager.setWebhook('inbox', 'https://example.com/wa', 's3cret');
    const sock = h.sockets[0];
    sock.ev.emit('messages.upsert', {
      type: 'notify',
      messages: [
        { key: { remoteJid: '5511888888888@s.whatsapp.net', fromMe: false, id: 'IN1' }, message: { conversation: 'olá' }, messageTimestamp: 1700000000 },
        { key: { remoteJid: '5511888888888@s.whatsapp.net', fromMe: true, id: 'OWN' }, message: { conversation: 'skip me' }, messageTimestamp: 1 },
        { key: { remoteJid: 'grupo@g.us', fromMe: false, id: 'GRP' }, message: { conversation: 'skip group' }, messageTimestamp: 1 },
        { key: { remoteJid: 'status@broadcast', fromMe: false, id: 'ST' }, message: { conversation: 'skip status' }, messageTimestamp: 1 },
        { key: { remoteJid: '5511888888888@s.whatsapp.net', fromMe: false, id: 'NOMEDIA' }, message: { imageMessage: {} }, messageTimestamp: 1 },
      ],
    });
    await new Promise((r) => setImmediate(r)); // let fire-and-forget run
    assert.equal(delivered.length, 1);
    assert.equal(delivered[0].url, 'https://example.com/wa');
    assert.equal(delivered[0].secret, 's3cret');
    assert.deepEqual(delivered[0].payload, {
      event: 'message.received',
      instance_id: 'inbox',
      message_id: 'IN1',
      from: '5511888888888',
      text: 'olá',
      timestamp: 1700000000,
    });
  });

  it('drops inbound when no webhook is configured', async () => {
    const delivered = [];
    const h = makeHarness();
    h.manager.deliverWebhook = async (args) => {
      delivered.push(args);
    };
    await h.manager.create('nowebhook');
    h.sockets[0].ev.emit('messages.upsert', {
      type: 'notify',
      messages: [
        { key: { remoteJid: '5511888888888@s.whatsapp.net', fromMe: false, id: 'IN2' }, message: { conversation: 'hi' }, messageTimestamp: 1 },
      ],
    });
    await new Promise((r) => setImmediate(r));
    assert.equal(delivered.length, 0);
  });
});

describe('SessionStore', () => {
  it('lists persisted session dirs and clears them', async () => {
    const base = await fs.mkdtemp(path.join(os.tmpdir(), 'sess-'));
    const store = new SessionStore(base);
    await fs.mkdir(path.join(base, 'inst-9'), { recursive: true });
    assert.deepEqual(await store.listIds(), ['inst-9']);
    assert.equal(await store.exists('inst-9'), true);
    await store.clear('inst-9');
    assert.equal(await store.exists('inst-9'), false);
    await fs.rm(base, { recursive: true, force: true });
  });

  it('round-trips JSON sidecars', async () => {
    const base = await fs.mkdtemp(path.join(os.tmpdir(), 'sess-'));
    const store = new SessionStore(base);
    assert.equal(await store.readMeta('i1', 'webhook.json'), null);
    await store.writeMeta('i1', 'webhook.json', { url: 'https://x.test' });
    assert.deepEqual(await store.readMeta('i1', 'webhook.json'), { url: 'https://x.test' });
    await fs.rm(base, { recursive: true, force: true });
  });
});

describe('defaultDeliverWebhook', () => {
  it('POSTs JSON with secret header', async () => {
    const received = [];
    const server = http.createServer((req, res) => {
      let body = '';
      req.on('data', (c) => (body += c));
      req.on('end', () => {
        received.push({ secret: req.headers['x-webhook-secret'], body: JSON.parse(body) });
        res.writeHead(200);
        res.end('ok');
      });
    });
    await new Promise((r) => server.listen(0, r));
    const silent = { info() {}, warn() {}, error() {} };
    await defaultDeliverWebhook({
      url: `http://127.0.0.1:${server.address().port}/hook`,
      secret: 's3cret',
      payload: { event: 'message.received', instance_id: 'i' },
      log: silent,
    });
    server.close();
    assert.equal(received.length, 1);
    assert.equal(received[0].secret, 's3cret');
    assert.equal(received[0].body.event, 'message.received');
  });

  it('gives up after retries on unreachable url', async () => {
    const silent = { info() {}, warn() {}, error() {} };
    await defaultDeliverWebhook({
      url: 'http://127.0.0.1:1/unreachable',
      secret: null,
      payload: { event: 'message.received', instance_id: 'i', from: '5511000000000' },
      log: silent,
    }); // must resolve, never throw
  });
});
