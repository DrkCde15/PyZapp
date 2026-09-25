'use strict';

require('dotenv').config();

const express = require('express');
const config = require('./config');
const { logger } = require('./logger');
const { SessionStore } = require('./whatsapp/session');
const { WhatsAppManager } = require('./whatsapp/manager');
const { internalAuth, fail } = require('./middleware/auth');
const { errorHandler } = require('./middleware/errorHandler');
const { buildInternalRoutes } = require('./routes/internal');
const { buildHealthRoutes } = require('./routes/health');

function buildApp(manager) {
  const app = express();
  app.disable('x-powered-by');
  // 20mb accommodates base64 media (capped at 12MB binary upstream).
  // This service is internal-only; the public API enforces its own limits.
  app.use(express.json({ limit: '20mb' }));

  // Structured request log (no bodies, no secrets).
  app.use((req, res, next) => {
    req.log = logger.child({ instance_id: req.params?.id });
    const start = Date.now();
    res.on('finish', () => {
      logger.info(
        {
          event: 'http_request',
          method: req.method,
          path: req.path,
          status_code: res.statusCode,
          duration_ms: Date.now() - start,
        },
        'request'
      );
    });
    next();
  });

  const startedAt = Date.now();
  app.use(buildHealthRoutes(manager, startedAt));
  app.use('/internal', internalAuth, buildInternalRoutes(manager));

  app.use((_req, res) => res.status(404).json(fail('not_found', 'Route not found')));
  // eslint-disable-next-line no-unused-vars
  app.use(errorHandler);

  return app;
}

async function main() {
  const sessionStore = new SessionStore(config.sessionDir);

  // Fan-out of inbound events to the API (AI auto-reply intake).
  const eventsSink = config.eventsUrl
    ? async (payload) => {
        const resp = await fetch(config.eventsUrl, {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            ...(config.internalApiKey ? { 'x-internal-key': config.internalApiKey } : {}),
          },
          body: JSON.stringify(payload),
          signal: AbortSignal.timeout(5000),
        });
        if (!resp.ok) throw new Error(`events sink HTTP ${resp.status}`);
      }
    : null;
  if (eventsSink) {
    logger.info({ event: 'events_sink_enabled' }, 'Inbound events fan-out enabled');
  }

  const manager = new WhatsAppManager({ sessionStore, eventsSink });
  const app = buildApp(manager);

  const server = app.listen(config.port, () => {
    logger.info(
      { event: 'startup', port: config.port, env: config.nodeEnv, session_dir: config.sessionDir },
      'Baileys service listening'
    );
  });

  // Restore persisted sessions without blocking startup.
  manager
    .restore()
    .then((n) => logger.info({ event: 'restore_done', instances: n }, 'Session restore finished'))
    .catch((err) => logger.error({ event: 'restore_failed', error: err.message }, 'Session restore failed'));

  const shutdown = (signal) => {
    logger.info({ event: 'shutdown', signal }, 'Shutting down');
    server.close(async () => {
      await manager.shutdown();
      process.exit(0);
    });
    setTimeout(() => process.exit(1), 10_000).unref();
  };
  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));
}

if (require.main === module) {
  main().catch((err) => {
    logger.error({ event: 'fatal', error: err.message }, 'Fatal startup error');
    process.exit(1);
  });
}

module.exports = { buildApp };
