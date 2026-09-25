'use strict';

const {
  InstanceNotFoundError,
  InstanceExistsError,
  assertValidInstanceId,
} = require('../errors');
const { logger, maskPhone } = require('../logger');
const { WhatsAppInstance } = require('./instance');

const WEBHOOK_TIMEOUT_MS = 5000;
const WEBHOOK_MAX_ATTEMPTS = 3;

/**
 * Default webhook delivery: POST JSON with retries + backoff.
 * Fire-and-forget from the message path; failures only surface in logs.
 */
async function defaultDeliverWebhook({ url, secret, payload, log }) {
  const headers = { 'content-type': 'application/json' };
  if (secret) headers['x-webhook-secret'] = secret;
  let attempt = 0;
  let delayMs = 1000;
  for (;;) {
    attempt += 1;
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(WEBHOOK_TIMEOUT_MS),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      log.info(
        { event: 'webhook_delivered', instance_id: payload.instance_id, attempt },
        'Webhook delivered'
      );
      return;
    } catch (err) {
      if (attempt >= WEBHOOK_MAX_ATTEMPTS) {
        log.error(
          {
            event: 'webhook_failed',
            instance_id: payload.instance_id,
            from: maskPhone(payload.from),
            attempts: attempt,
            error: err.message,
          },
          'Webhook delivery failed'
        );
        return;
      }
      await new Promise((r) => setTimeout(r, delayMs));
      delayMs *= 2;
    }
  }
}

/**
 * Owns all WhatsAppInstance objects. Routes must go through here and
 * never touch Baileys directly:
 *
 *   Route -> WhatsAppManager -> WhatsAppInstance -> Baileys
 */
class WhatsAppManager {
  constructor({ sessionStore, socketFactory, deliverWebhook, log } = {}) {
    if (!sessionStore) throw new Error('WhatsAppManager requires a sessionStore');
    this.sessionStore = sessionStore;
    this.socketFactory = socketFactory;
    this.deliverWebhook = deliverWebhook || defaultDeliverWebhook;
    this.log = log || logger;
    this.instances = new Map();
  }

  _wire(instance) {
    instance.onInbound = (payload) => {
      const webhook = instance.webhook;
      if (!webhook?.url) {
        this.log.info(
          { event: 'inbound_no_webhook', instance_id: payload.instance_id },
          'Inbound message dropped: no webhook configured'
        );
        return;
      }
      // Fire-and-forget: never block the Baileys event loop.
      this.deliverWebhook({ url: webhook.url, secret: webhook.secret, payload, log: this.log }).catch(
        (err) => this.log.error({ event: 'webhook_error', error: err.message }, 'Webhook error')
      );
    };
    return instance;
  }

  /** Create + start connecting so a QR is available right away. */
  async create(instanceId) {
    assertValidInstanceId(instanceId);
    if (this.instances.has(instanceId)) throw new InstanceExistsError(instanceId);
    const instance = new WhatsAppInstance({
      id: instanceId,
      sessionStore: this.sessionStore,
      socketFactory: this.socketFactory,
    });
    this.instances.set(instanceId, instance);
    this._wire(instance);
    this.log.info({ event: 'instance_created', instance_id: instanceId }, 'Instance created');
    try {
      await instance.connect();
    } catch (err) {
      // Creation succeeds even if the first socket attempt fails;
      // the failure is visible via status and retried automatically.
      this.log.error(
        { event: 'initial_connect_failed', instance_id: instanceId, error: err.message },
        'Initial connect failed'
      );
    }
    return instance.snapshot();
  }

  get(instanceId) {
    const instance = this.instances.get(instanceId);
    if (!instance) throw new InstanceNotFoundError(instanceId);
    return instance;
  }

  list() {
    return [...this.instances.values()].map((i) => i.snapshot());
  }

  count() {
    return this.instances.size;
  }

  async connect(instanceId) {
    return (await this._require(instanceId)).connect();
  }

  async requestPairingCode(instanceId, phone) {
    return (await this._require(instanceId)).requestPairingCode(phone);
  }

  async setWebhook(instanceId, url, secret = null) {
    return (await this._require(instanceId)).setWebhook(url, secret);
  }

  async delete(instanceId) {
    const instance = this._require(instanceId);
    await instance.destroy({ clearSession: true });
    this.instances.delete(instanceId);
    this.log.info({ event: 'instance_deleted', instance_id: instanceId }, 'Instance deleted');
  }

  /** Re-create instances that have persisted sessions (service restart). */
  async restore() {
    const ids = await this.sessionStore.listIds();
    for (const id of ids) {
      try {
        assertValidInstanceId(id);
        if (this.instances.has(id)) continue;
        const instance = new WhatsAppInstance({
          id,
          sessionStore: this.sessionStore,
          socketFactory: this.socketFactory,
        });
        this.instances.set(id, instance);
        this._wire(instance);
        await instance.loadWebhook();
        await instance.connect();
        this.log.info({ event: 'instance_restored', instance_id: id }, 'Session restored');
      } catch (err) {
        this.log.error(
          { event: 'restore_failed', instance_id: id, error: err.message },
          'Failed to restore session'
        );
      }
    }
    return this.count();
  }

  /** Close all sockets without wiping sessions (graceful shutdown). */
  async shutdown() {
    for (const instance of this.instances.values()) {
      try {
        await instance.destroy({ clearSession: false });
      } catch {
        // best effort
      }
    }
    this.instances.clear();
  }

  _require(instanceId) {
    assertValidInstanceId(instanceId);
    return this.get(instanceId);
  }
}

module.exports = { WhatsAppManager, defaultDeliverWebhook };
