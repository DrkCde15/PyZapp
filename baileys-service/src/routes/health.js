'use strict';

const { Router } = require('express');

function buildHealthRoutes(manager, startedAt) {
  const router = Router();

  router.get('/health', (_req, res) => {
    res.json({
      status: 'ok',
      service: 'baileys',
      instances: manager.count(),
      uptime_s: Math.floor((Date.now() - startedAt) / 1000),
    });
  });

  return router;
}

module.exports = { buildHealthRoutes };
