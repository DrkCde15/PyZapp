'use strict';

/**
 * Typed errors with stable `code` values and HTTP mappings.
 * These codes are part of the internal contract with FastAPI,
 * which translates them into public API errors.
 */
class ServiceError extends Error {
  constructor(code, message, statusCode = 500) {
    super(message);
    this.name = this.constructor.name;
    this.code = code;
    this.statusCode = statusCode;
  }
}

class InstanceNotFoundError extends ServiceError {
  constructor(instanceId) {
    super('instance_not_found', `Instance '${instanceId}' not found`, 404);
  }
}

class InstanceExistsError extends ServiceError {
  constructor(instanceId) {
    super('instance_exists', `Instance '${instanceId}' already exists`, 409);
  }
}

class InstanceNotConnectedError extends ServiceError {
  constructor(instanceId) {
    super('not_connected', `Instance '${instanceId}' is not connected`, 409);
  }
}

class QrNotAvailableError extends ServiceError {
  constructor(instanceId, status) {
    super(
      'qr_not_available',
      `No QR code available for instance '${instanceId}' (status: ${status})`,
      409
    );
    this.status = status;
  }
}

class InvalidInputError extends ServiceError {
  constructor(message) {
    super('invalid_input', message, 400);
  }
}

class BaileysOperationError extends ServiceError {
  constructor(message) {
    super('baileys_error', message, 502);
  }
}

class ConnectionNotReadyError extends ServiceError {
  constructor(instanceId) {
    super('connection_not_ready', `Instance '${instanceId}' is still connecting; retry shortly`, 409);
  }
}

const INSTANCE_ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

function assertValidInstanceId(instanceId) {
  if (!instanceId || !INSTANCE_ID_RE.test(instanceId)) {
    throw new InvalidInputError(
      'Invalid instance_id: use 1-64 chars of letters, numbers, "-" or "_"'
    );
  }
}

/** Normalize a phone number to digits-only; throws on invalid input. */
function normalizePhone(phone) {
  const digits = String(phone || '').replace(/\D/g, '');
  if (!/^[1-9]\d{7,14}$/.test(digits)) {
    throw new InvalidInputError(
      'Invalid phone: expected E.164 digits with country code (8-15 digits)'
    );
  }
  return digits;
}

/** Convert a phone number to a WhatsApp JID. */
function toJid(phone) {
  return `${normalizePhone(phone)}@s.whatsapp.net`;
}

module.exports = {
  ServiceError,
  InstanceNotFoundError,
  InstanceExistsError,
  InstanceNotConnectedError,
  QrNotAvailableError,
  InvalidInputError,
  BaileysOperationError,
  ConnectionNotReadyError,
  assertValidInstanceId,
  normalizePhone,
  toJid,
};
