'use strict';

const { Router } = require('express');
const { InvalidInputError } = require('../errors');
const { ok } = require('../middleware/auth');
const { maskPhone } = require('../logger');

/**
 * Internal API consumed exclusively by FastAPI.
 * No Baileys logic lives here: everything delegates to WhatsAppManager.
 */
function buildInternalRoutes(manager) {
  const router = Router();

  router.post('/instances', async (req, res, next) => {
    try {
      const { instance_id } = req.body || {};
      const snapshot = await manager.create(instance_id);
      return res.status(201).json(ok(snapshot));
    } catch (err) {
      return next(err);
    }
  });

  router.get('/instances', (_req, res) => res.json(ok(manager.list())));

  router.get('/instances/:id/status', (req, res, next) => {
    try {
      const snap = manager.get(req.params.id).snapshot();
      return res.json(
        ok({
          instance_id: snap.instance_id,
          status: snap.status,
          connected: snap.connected,
          phone: snap.phone,
          updated_at: snap.updated_at,
        })
      );
    } catch (err) {
      return next(err);
    }
  });

  router.get('/instances/:id/qr', (req, res, next) => {
    try {
      return res.json(ok(manager.get(req.params.id).getQr()));
    } catch (err) {
      return next(err);
    }
  });

  router.post('/instances/:id/connect', async (req, res, next) => {
    try {
      const snap = await manager.connect(req.params.id);
      return res.status(202).json(ok(snap));
    } catch (err) {
      return next(err);
    }
  });

  router.post('/instances/:id/messages', async (req, res, next) => {    try {
      const { to, text } = req.body || {};
      if (typeof to !== 'string' || !to.trim()) {
        throw new InvalidInputError('Field "to" is required');
      }
      const messageId = await manager.get(req.params.id).sendText(to, text);
      req.log.info(
        { event: 'message_sent', instance_id: req.params.id, to: maskPhone(to), message_id: messageId },
        'Message sent'
      );
      return res.json(ok({ message_id: messageId }));
    } catch (err) {
      return next(err);
    }
  });

  router.post('/instances/:id/pairing-code', async (req, res, next) => {
    try {
      const { phone } = req.body || {};
      if (typeof phone !== 'string' || !phone.trim()) {
        throw new InvalidInputError('Field "phone" is required');
      }
      const pairingCode = await manager.requestPairingCode(req.params.id, phone);
      return res.json(ok({ pairing_code: pairingCode }));
    } catch (err) {
      return next(err);
    }
  });

  router.put('/instances/:id/webhook', async (req, res, next) => {
    try {
      const { url, secret = null } = req.body || {};
      if (typeof url !== 'string' || !url.trim()) {
        throw new InvalidInputError('Field "url" is required');
      }
      const webhook = await manager.setWebhook(req.params.id, url, secret);
      return res.json(ok({ url: webhook.url, configured: true }));
    } catch (err) {
      return next(err);
    }
  });

  router.delete('/instances/:id', async (req, res, next) => {
    try {
      await manager.delete(req.params.id);
      return res.json(ok({ instance_id: req.params.id }));
    } catch (err) {
      return next(err);
    }
  });

  return router;
}

module.exports = { buildInternalRoutes };
