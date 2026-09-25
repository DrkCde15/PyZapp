'use strict';

const config = require('../config');
const { logger } = require('../logger');

/**
 * Internal auth: only FastAPI (holder of INTERNAL_API_KEY) may call
 * /internal/*. Health stays public so orchestrators can probe it.
 */
function internalAuth(req, res, next) {
  if (!config.internalApiKey) {
    if (config.nodeEnv === 'production') {
      logger.error({ event: 'misconfigured' }, 'INTERNAL_API_KEY is required in production');
      return res.status(500).json(fail('misconfigured', 'Service misconfigured'));
    }
    logger.warn({ event: 'insecure_mode' }, 'INTERNAL_API_KEY unset: allowing internal calls (dev only)');
    return next();
  }
  const provided = req.header('x-internal-key');
  if (provided !== config.internalApiKey) {
    return res.status(401).json(fail('unauthorized', 'Invalid internal credentials'));
  }
  return next();
}

function fail(code, message, data) {
  return { success: false, error: { code, message }, ...(data ? { data } : {}) };
}

function ok(data) {
  return { success: true, data };
}

module.exports = { internalAuth, fail, ok };
