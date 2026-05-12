import response from './index.js';

describe('modules/response', () => {
  let mockResponse;

  beforeEach(() => {
    mockResponse = {
      status: jest.fn().mockReturnThis(),
      json: jest.fn().mockReturnThis()
    };
  });

  describe('.badRequest()', () => {
    test('should return 400 status with Bad Request message', () => {
      const message = { error: 'Invalid input' };

      const result = response.badRequest(mockResponse, message);

      expect(mockResponse.status).toHaveBeenCalledWith(400);
      expect(mockResponse.json).toHaveBeenCalledWith({
        status: 'Bad Request',
        error: 'Invalid input'
      });
      expect(result).toBe(mockResponse);
    });

    test('should handle empty message object', () => {
      const message = {};

      response.badRequest(mockResponse, message);

      expect(mockResponse.status).toHaveBeenCalledWith(400);
      expect(mockResponse.json).toHaveBeenCalledWith({
        status: 'Bad Request'
      });
    });

    test('should handle complex message object', () => {
      const message = {
        error: 'Validation failed',
        details: ['Field1 is required', 'Field2 must be a number'],
        code: 'VALIDATION_ERROR'
      };

      response.badRequest(mockResponse, message);

      expect(mockResponse.json).toHaveBeenCalledWith({
        status: 'Bad Request',
        error: 'Validation failed',
        details: ['Field1 is required', 'Field2 must be a number'],
        code: 'VALIDATION_ERROR'
      });
    });
  });

  describe('.internalServerError()', () => {
    test('should return 500 status with Internal Server Error message', () => {
      const message = { error: 'Database connection failed' };

      const result = response.internalServerError(mockResponse, message);

      expect(mockResponse.status).toHaveBeenCalledWith(500);
      expect(mockResponse.json).toHaveBeenCalledWith({
        status: 'Internal Server Error',
        error: 'Database connection failed'
      });
      expect(result).toBe(mockResponse);
    });

    test('should handle empty message object', () => {
      const message = {};

      response.internalServerError(mockResponse, message);

      expect(mockResponse.status).toHaveBeenCalledWith(500);
      expect(mockResponse.json).toHaveBeenCalledWith({
        status: 'Internal Server Error'
      });
    });
  });

  describe('.notFound()', () => {
    test('should return 404 status with Not Found message', () => {
      const message = { error: 'Resource not found' };

      const result = response.notFound(mockResponse, message);

      expect(mockResponse.status).toHaveBeenCalledWith(404);
      expect(mockResponse.json).toHaveBeenCalledWith({
        status: 'Not Found',
        error: 'Resource not found'
      });
      expect(result).toBe(mockResponse);
    });

    test('should handle message with resource details', () => {
      const message = {
        error: 'User not found',
        resource: 'user',
        id: '12345'
      };

      response.notFound(mockResponse, message);

      expect(mockResponse.json).toHaveBeenCalledWith({
        status: 'Not Found',
        error: 'User not found',
        resource: 'user',
        id: '12345'
      });
    });
  });

  describe('.blockedRequest()', () => {
    test('should return 403 status with Blocked Request message', () => {
      const message = { error: 'Access denied' };

      const result = response.blockedRequest(mockResponse, message);

      expect(mockResponse.status).toHaveBeenCalledWith(403);
      expect(mockResponse.json).toHaveBeenCalledWith({
        status: 'Blocked Request',
        error: 'Access denied'
      });
      expect(result).toBe(mockResponse);
    });

    test('should handle authorization details', () => {
      const message = {
        error: 'Insufficient permissions',
        required: 'admin',
        current: 'user'
      };

      response.blockedRequest(mockResponse, message);

      expect(mockResponse.json).toHaveBeenCalledWith({
        status: 'Blocked Request',
        error: 'Insufficient permissions',
        required: 'admin',
        current: 'user'
      });
    });
  });

  describe('.success()', () => {
    test('should return 200 status with Success message', () => {
      const message = { data: 'Operation completed' };

      const result = response.success(mockResponse, message);

      expect(mockResponse.status).toHaveBeenCalledWith(200);
      expect(mockResponse.json).toHaveBeenCalledWith({
        status: 'Success',
        data: 'Operation completed'
      });
      expect(result).toBe(mockResponse);
    });

    test('should handle complex success data', () => {
      const message = {
        data: {
          users: [{ id: 1, name: 'John' }, { id: 2, name: 'Jane' }],
          total: 2,
          page: 1
        },
        message: 'Users retrieved successfully'
      };

      response.success(mockResponse, message);

      expect(mockResponse.json).toHaveBeenCalledWith({
        status: 'Success',
        data: {
          users: [{ id: 1, name: 'John' }, { id: 2, name: 'Jane' }],
          total: 2,
          page: 1
        },
        message: 'Users retrieved successfully'
      });
    });

    test('should handle empty success message', () => {
      const message = {};

      response.success(mockResponse, message);

      expect(mockResponse.json).toHaveBeenCalledWith({
        status: 'Success'
      });
    });
  });
});
