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
  app.use(express.json({ limit: '256kb' }));

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
  const manager = new WhatsAppManager({ sessionStore });
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
