'use strict';

class ApiError extends Error {
  constructor(status, code, message, options = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.retryable = Boolean(options.retryable);
    this.details = options.details;
  }
}

function invalidArgument(message, details) {
  return new ApiError(400, 'INVALID_ARGUMENT', message, { details });
}

module.exports = { ApiError, invalidArgument };
