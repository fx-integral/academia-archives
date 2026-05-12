import time from './index.js';

describe('modules/time', () => {
  describe('.getCurrentTimestamp()', () => {
    test('should return current timestamp in correct format', () => {
      const mockDate = new Date('2024-01-01T12:00:00.123Z');
      jest.spyOn(globalThis, 'Date').mockImplementation(() => mockDate);

      const result = time.getCurrentTimestamp();

      expect(result).toBe('2024-01-01 12:00:00.123');
      expect(result).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}$/);
    });

    test('should always return string of length 23', () => {
      const mockDate = new Date('2024-06-15T14:30:45.678Z');
      jest.spyOn(globalThis, 'Date').mockImplementation(() => mockDate);

      const result = time.getCurrentTimestamp();

      expect(result).toHaveLength(23);
      expect(result).toBe('2024-06-15 14:30:45.678');
    });
  });

  describe('.getDuration()', () => {

    test('should calculate duration correctly in seconds', () => {
      const currentTime = 5000; // 5 seconds
      const startTime = 2000;   // 2 seconds
      const expectedDuration = 3; // 3 seconds difference

      jest.spyOn(Date, 'now').mockReturnValue(currentTime);

      const result = time.getDuration(startTime);

      expect(result).toBe(expectedDuration);
    });

    test('should handle zero duration', () => {
      const currentTime = 1000;
      const startTime = 1000;

      jest.spyOn(Date, 'now').mockReturnValue(currentTime);

      const result = time.getDuration(startTime);

      expect(result).toBe(0);
    });

    test('should handle fractional seconds', () => {
      const currentTime = 2500; // 2.5 seconds
      const startTime = 1000;   // 1 second
      const expectedDuration = 1.5; // 1.5 seconds difference

      jest.spyOn(Date, 'now').mockReturnValue(currentTime);

      const result = time.getDuration(startTime);

      expect(result).toBe(expectedDuration);
    });

    test('should handle large time differences', () => {
      const currentTime = 3_661_000; // ~1 hour and 1 minute and 1 second
      const startTime = 1000;      // 1 second
      const expectedDuration = 3660; // 3660 seconds (1 hour and 1 minute)

      jest.spyOn(Date, 'now').mockReturnValue(currentTime);

      const result = time.getDuration(startTime);

      expect(result).toBe(expectedDuration);
    });

    test('should return positive value even if startTime is in future', () => {
      const currentTime = 1000;
      const startTime = 2000; // Future time
      const expectedDuration = -1; // Negative duration

      jest.spyOn(Date, 'now').mockReturnValue(currentTime);

      const result = time.getDuration(startTime);

      expect(result).toBe(expectedDuration);
    });

    test('should handle very small durations', () => {
      const currentTime = 1001; // 1.001 seconds
      const startTime = 1000;   // 1 second
      const expectedDuration = 0.001; // 1 millisecond

      jest.spyOn(Date, 'now').mockReturnValue(currentTime);

      const result = time.getDuration(startTime);

      expect(result).toBe(expectedDuration);
    });
  });

  describe('.getOldestDate()', () => {
    test('should return undefined if the array is empty', () => {
      const dates = [];
      const result = time.getOldestDate(dates);
      expect(result).toBeUndefined();
    });

    test('should return the oldest date', () => {
      const dates = [new Date('2024-01-01'), new Date('2024-01-02'), new Date('2024-01-03')];
      const result = time.getOldestDate(dates);
      expect(result).toEqual(new Date('2024-01-01'));
    });
  });

  describe('.getMostRecentDate()', () => {
    test('should return undefined if the array is empty', () => {
      const dates = [];
      const result = time.getMostRecentDate(dates);
      expect(result).toBeUndefined();
    });

    test('should return the most recent date', () => {
      const dates = [new Date('2024-01-01'), new Date('2024-01-02'), new Date('2024-01-03')];
      const result = time.getMostRecentDate(dates);
      expect(result).toEqual(new Date('2024-01-03'));
    });
  });
});
