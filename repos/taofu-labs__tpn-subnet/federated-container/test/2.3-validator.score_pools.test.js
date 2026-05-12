import { test, describe } from 'node:test'
import assert from 'node:assert'
import { json } from './_helpers.js'
import { BASE_URL } from './_fixtures.js'

describe( '/validator/score/force endpoint', () => {


    test( 'should return mining pool scores if CI_MODE is enabled', async () => {
        // Set CI_MODE for this test
        const { response, data } = await json.get( `${ BASE_URL }/validator/score/force` )
        assert.strictEqual( response.status, 200 )
        assert.ok( typeof data === 'object' && data !== null )
        // Each key should be a mining_pool_uid, value should have expected keys
        for( const [ uid, pool ] of Object.entries( data ) ) {
            assert.ok( pool )
            assert.ok( typeof pool.mining_pool_ip === 'string' )
            assert.ok( typeof pool.score === 'number' )
            assert.ok( typeof pool.stability_score === 'number' )
            assert.ok( typeof pool.geo_score === 'number' )
            assert.ok( typeof pool.size_score === 'number' )
            assert.ok( typeof pool.performance_score === 'number' )
        }
    } )
} )
