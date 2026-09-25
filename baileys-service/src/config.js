'use strict';

/**
 * Centralized configuration. Everything comes from environment variables.
 * Never hardcode secrets here.
 */
const config = {
  port: parseInt(process.env.BAILEYS_PORT || '3001', 10),
  // Shared secret used by FastAPI to call this service. Empty = allowed
  // only outside production (with a warning) to keep local dev simple.
  internalApiKey: process.env.INTERNAL_API_KEY || '',
  nodeEnv: process.env.NODE_ENV || 'development',
  sessionDir: process.env.SESSION_DIR || './sessions',
  logLevel: process.env.LOG_LEVEL || 'info',
  // Where inbound message events are fanned out for AI auto-reply.
  // Empty = disabled (user webhooks still work).
  eventsUrl: process.env.EVENTS_URL || '',
};

module.exports = config;
