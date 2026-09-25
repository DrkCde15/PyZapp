'use strict';

const { logger } = require('../logger');
const { ServiceError } = require('../errors');
const { fail } = require('./auth');

/** Final error mapper: typed errors -> stable codes, rest -> 500. */
function errorHandler(err, req, res, _next) {
  if (err instanceof ServiceError) {
    if (err.code === 'qr_not_available') {
      return res.status(err.statusCode).json(fail(err.code, err.message, { status: err.status }));
    }
    return res.status(err.statusCode).json(fail(err.code, err.message));
  }
  if (err?.type === 'entity.parse.failed') {
    return res.status(400).json(fail('invalid_input', 'Malformed JSON body'));
  }
  logger.error(
    { event: 'unhandled_error', method: req.method, path: req.path, error: err?.message },
    'Unhandled error'
  );
  return res.status(500).json(fail('internal_error', 'Internal service error'));
}

module.exports = { errorHandler };
