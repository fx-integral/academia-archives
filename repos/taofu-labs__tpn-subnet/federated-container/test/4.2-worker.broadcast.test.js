import { test, describe } from 'node:test'
import assert from 'node:assert'
import { json } from './_helpers.js'
import { BASE_URL } from './_fixtures.js'

// Tests for the /worker/register/force endpoint
// Behavior:
// - Only available when server runs in worker mode (otherwise may return 404)
// - Requires CI_MODE=true, otherwise 403 with JSON error
// - When allowed, triggers registration and returns JSON with { registered, worker }
//   but this may fail with 500 if MINING_POOL_URL or dependencies are not available.

describe( '/worker/register/force (worker mode)', () => {

    test( 'Returns 200 and json response with worker key', async () => {
        const { response, data } = await json.get( `${ BASE_URL }/worker/register/force` )
        assert.strictEqual( response.status, 200 )
        assert.ok( data && typeof data === 'object' )
        assert.ok( 'worker' in data )
    } )

} )
