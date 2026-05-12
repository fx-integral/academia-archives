/* eslint-disable no-console */
import logger from './index.js';
import time from '#modules/time/index.js';

jest.mock('#modules/time/index.js');
jest.mock('chalk', () => ({
  green: jest.fn((text) => `GREEN:${text}`),
  yellow: jest.fn((text) => `YELLOW:${text}`),
  red: jest.fn((text) => `RED:${text}`)
}));

describe('modules/logger', () => {
  const mockTimestamp = '2024-01-01 12:00:00.000';

  beforeEach(() => {
    time.getCurrentTimestamp.mockReturnValue(mockTimestamp);

    jest.spyOn(console, 'log').mockImplementation();
    jest.spyOn(console, 'error').mockImplementation();
  });
  describe('.info()', () => {
    test('should log info message with timestamp and green color', () => {
      const message = 'Test info message';

      logger.info(message);

      expect(time.getCurrentTimestamp).toHaveBeenCalled();
      expect(console.log).toHaveBeenCalledWith(
        `GREEN:${mockTimestamp} [INFO] ${message}`
      );
    });

    test('should log info message with additional arguments', () => {
      const message = 'Test info message';
      const argument1 = { key: 'value' };
      const argument2 = 'additional';

      logger.info(message, argument1, argument2);

      expect(console.log).toHaveBeenCalledWith(
        `GREEN:${mockTimestamp} [INFO] ${message}`,
        argument1,
        argument2
      );
    });

    test('should handle empty message', () => {
      logger.info('');

      expect(console.log).toHaveBeenCalledWith(
        `GREEN:${mockTimestamp} [INFO] `
      );
    });
  });

  describe('.warning()', () => {
    test('should log warning message with timestamp and yellow color', () => {
      const message = 'Test warning message';

      logger.warning(message);

      expect(time.getCurrentTimestamp).toHaveBeenCalled();
      expect(console.log).toHaveBeenCalledWith(
        `YELLOW:${mockTimestamp} [WARNING] ${message}`
      );
    });

    test('should log warning message with additional arguments', () => {
      const message = 'Test warning message';
      const argument1 = ['array', 'data'];

      logger.warning(message, argument1);

      expect(console.log).toHaveBeenCalledWith(
        `YELLOW:${mockTimestamp} [WARNING] ${message}`,
        argument1
      );
    });
  });

  describe('.error()', () => {
    test('should log error message with timestamp and red color', () => {
      const message = 'Test error message';

      logger.error(message);

      expect(time.getCurrentTimestamp).toHaveBeenCalled();
      expect(console.error).toHaveBeenCalledWith(
        `RED:${mockTimestamp} [ERROR] ${message}`
      );
    });

    test('should log error message with Error object', () => {
      const message = 'Test error message';
      const error = new Error('Detailed error');

      logger.error(message, error);

      expect(console.error).toHaveBeenCalledWith(
        `RED:${mockTimestamp} [ERROR] ${message}`,
        error
      );
    });

    test('should log error message with multiple arguments', () => {
      const message = 'Test error message';
      const errorCode = 500;
      const errorDetails = { stack: 'error stack' };

      logger.error(message, errorCode, errorDetails);

      expect(console.error).toHaveBeenCalledWith(
        `RED:${mockTimestamp} [ERROR] ${message}`,
        errorCode,
        errorDetails
      );
    });
  });
});
