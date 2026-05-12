import apify from './index.js';

jest.mock('apify-client', () => ({
  ApifyClient: jest.fn().mockImplementation(() => ({
    actor: jest.fn().mockReturnValue({
      call: jest.fn().mockResolvedValue({
        defaultDatasetId: 'mock-dataset-id'
      })
    }),
    dataset: jest.fn().mockReturnValue({
      listItems: jest.fn().mockResolvedValue({
        items: [
          { id: 1, review: 'Mock review 1' },
          { id: 2, review: 'Mock review 2' }
        ]
      })
    })
  }))
}));
jest.mock('#modules/logger/index.js', () => ({
  info: jest.fn(),
  warning: jest.fn(),
  error: jest.fn()
}));

describe('modules/apify', () => {

  describe('.runActorAndGetResults()', () => {
    test('should be able to return the results of the actor run', async () => {
      const result = await apify.runActorAndGetResults('test-actor', {
        placeFIDs: ['1234567890'],
        maxItems: 10,
        language: 'en',
        sort: 'newest'
      });

      expect(result).toEqual([{
        id: 1,
        review: 'Mock review 1'
      }, {
        id: 2,
        review: 'Mock review 2'
      }]);
    });
  });
});
