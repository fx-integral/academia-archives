/**
 * Bad Request
 * @param {import('express').Response} response - The response object
 * @param {Object} message - The message object
 * @returns {import('express').Response}
 */
function badRequest(response, message) {
  return response.status(400).json({
    status: 'Bad Request',
    ...message,
  });
}

/**
 * Internal Server Error
 * @param {import('express').Response} response - The response object
 * @param {Object} message - The message object
 * @returns {import('express').Response}
 */
function internalServerError(response, message) {
  return response.status(500).json({
    status: 'Internal Server Error',
    ...message,
  });
}

/**
 * Not Found
 * @param {import('express').Response} response - The response object
 * @param {Object} message - The message object
 * @returns {import('express').Response}
 */
function notFound(response, message) {
  return response.status(404).json({
    status: 'Not Found',
    ...message,
  });
}

function blockedRequest(response, message) {
  return response.status(403).json({
    status: 'Blocked Request',
    ...message,
  });
}

function success(response, message) {
  return response.status(200).json({
    status: 'Success',
    ...message,
  });
}

export default {
  badRequest,
  internalServerError,
  notFound,
  blockedRequest,
  success
};
