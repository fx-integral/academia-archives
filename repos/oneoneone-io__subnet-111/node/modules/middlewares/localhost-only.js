import logger from '#modules/logger/index.js';
import responseService from '#modules/response/index.js';

/**
 * Localhost validation middleware
 * @param {import('express').Request} request - The request object
 * @param {import('express').Response} response - The response object
 * @param {import('express').NextFunction} next - The next function
 * @returns {void}
 */
const localhostOnly = (request, response, next) => {
  const ip = request.ip || request.connection.remoteAddress;
  const isLocalhost = ip === '127.0.0.1' || ip === '::1' || ip === '::ffff:127.0.0.1' || ip.includes('localhost');

  if (!isLocalhost) {
    logger.warning(`[Miner] Blocked request from unauthorized IP: ${ip}`);
    return responseService.blockedRequest(response, { error: 'Access denied. Only localhost requests are allowed.' });
  }

  next();
};

export default localhostOnly;
