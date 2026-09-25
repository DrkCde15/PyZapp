'use strict';

const pino = require('pino');
const config = require('./config');

const logger = pino({
  level: config.logLevel,
  base: { service: 'baileys' },
  // Never log credential material. QR payloads and auth files are safe to
  // reference (e.g. "qr refreshed") but must never be dumped into logs.
  redact: {
    paths: ['*.password', '*.token', '*.creds', '*.qr'],
    remove: true,
  },
});

/** Child logger scoped to one WhatsApp instance. */
function withInstance(instanceId, extra = {}) {
  return logger.child({ instance_id: instanceId, ...extra });
}

/** Mask a phone number for logs: keep country prefix + last 2 digits. */
function maskPhone(phone) {
  const digits = String(phone || '').replace(/\D/g, '');
  if (digits.length <= 4) return '****';
  return `${digits.slice(0, 2)}****${digits.slice(-2)}`;
}

module.exports = { logger, withInstance, maskPhone };
