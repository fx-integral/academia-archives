import { test, describe } from 'node:test'
import assert from 'node:assert'
import { json } from './_helpers.js'
import { BASE_URL } from './_fixtures.js'

// Tests for the /api/lease/new endpoint in miner mode
// These tests are written to be resilient whether the WireGuard container is mocked or not.
// If the backend is not fully mocked, the endpoint should return a 500 with an error payload.
// If it is mocked/available, a 200 response is acceptable and validated for basic shape.

describe( 'GET /api/lease/new (miner mode)', () => {

    test( 'returns 500 when required lease_seconds is missing', async () => {
        const { response, data } = await json.get( `${ BASE_URL }/api/lease/new?geo=any&format=json` )
        assert.strictEqual( response.status, 500 )
        assert.ok( data && typeof data === 'object' )
        assert.ok( typeof data.error === 'string' && data.error.toLowerCase().includes( 'error handling new lease route' ) )
    } )

    test( 'returns 500 when lease_seconds is not a number', async () => {
        console.log( `${ BASE_URL }/api/lease/new?geo=any&lease_seconds=abc&format=json` )
        const { response, data } = await json.get( `${ BASE_URL }/api/lease/new?geo=any&lease_seconds=abc&format=json` )
        assert.strictEqual( response.status, 500 )
        assert.ok( data && typeof data === 'object' )
        assert.ok( typeof data.error === 'string' )
    } )

    test( 'returns 500 when format is invalid', async () => {
        const { response, data } = await json.get( `${ BASE_URL }/api/lease/new?geo=any&lease_seconds=60&format=xml` )
        assert.strictEqual( response.status, 500 )
        assert.ok( data && typeof data === 'object' )
        assert.ok( typeof data.error === 'string' )
    } )

    test( 'supports format=text returns text', async () => {
        const config = await fetch( `${ BASE_URL }/api/lease/new?geo=any&lease_seconds=60&format=text` ).then( r => r.text() )

        assert.ok( typeof config === 'string' && config.length > 0 )

    } )

    test( 'supports format=json returns JSON', async () => {
        const { response, data } = await json.get( `${ BASE_URL }/api/lease/new?geo=any&lease_seconds=60&format=json` )
        // When mocked/available, should return a JSON object representing the config
        assert.ok( typeof data === 'object' && data !== null )
        assert.strictEqual( response.status, 200 )
    } )

} )