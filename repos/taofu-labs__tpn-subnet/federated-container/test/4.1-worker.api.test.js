import { test, describe } from 'node:test'
import assert from 'node:assert'
import { json } from './_helpers.js'
import { BASE_URL } from './_fixtures.js'

// Tests for the /api/lease/new endpoint in worker mode
// These tests are written to be resilient whether the WireGuard container is mocked or not.
// If the backend is not fully mocked, the endpoint should return a 500 with an error payload.
// If it is mocked/available, a 200 response is acceptable and validated for basic shape.

describe( 'GET /api/lease/new (worker mode)', () => {

    test( 'returns 500 when required lease_seconds is missing', async () => {
        const { response, data } = await json.get( `${ BASE_URL }/api/lease/new?format=json` )
        assert.strictEqual( response.status, 500 )
        assert.ok( data && typeof data === 'object' )
        assert.ok( typeof data.error === 'string' && data.error.toLowerCase().includes( 'error handling new lease route' ) )
    } )

    test( 'returns 500 when lease_seconds is not a number', async () => {
        const { response, data } = await json.get( `${ BASE_URL }/api/lease/new?lease_seconds=abc&format=json` )
        assert.strictEqual( response.status, 500 )
        assert.ok( data && typeof data === 'object' )
        assert.ok( typeof data.error === 'string' )
    } )

    test( 'returns 500 when format is invalid', async () => {
        const { response, data } = await json.get( `${ BASE_URL }/api/lease/new?lease_seconds=60&format=xml` )
        assert.strictEqual( response.status, 500 )
        assert.ok( data && typeof data === 'object' )
        assert.ok( typeof data.error === 'string' )
    } )


    test( 'supports format=text returns text', async () => {
        const config = await fetch( `${ BASE_URL }/api/lease/new?lease_seconds=60&format=text` ).then( r => r.text() )

        assert.ok( typeof config === 'string' && config.length > 0 )

    } )

    test( 'supports format=json returns JSON', async () => {
        console.log( `${ BASE_URL }/api/lease/new?lease_seconds=60&format=json` )
        const { response, data } = await json.get( `${ BASE_URL }/api/lease/new?lease_seconds=60&format=json` )
        // When mocked/available, should return a JSON object representing the config
        assert.ok( typeof data === 'object' && data !== null )
        assert.strictEqual( response.status, 200 )
    } )

} )

describe( 'GET /api/lease/countries (worker mode)', () => {

    test( 'returns countries in JSON format with country codes by default', async () => {
        const { response, data } = await json.get( `${ BASE_URL }/api/lease/countries` )
        
        assert.strictEqual( response.status, 200 )
        assert.ok( Array.isArray( data ) )
        // Should return array of country codes (2-letter strings)
        if( data.length > 0 ) {
            assert.ok( data.every( code => typeof code === 'string' && code.length === 2 ) )
        }
    } )

    test( 'returns countries in JSON format with country names when type=name', async () => {
        const { response, data } = await json.get( `${ BASE_URL }/api/lease/countries?type=name` )
        
        assert.strictEqual( response.status, 200 )
        assert.ok( Array.isArray( data ) )
        // Should return array of country names (longer strings)
        if( data.length > 0 ) {
            assert.ok( data.every( name => typeof name === 'string' && name.length > 2 ) )
        }
    } )

    test( 'returns countries in text format when format=text', async () => {
        const response = await fetch( `${ BASE_URL }/api/lease/countries?format=text` )
        const text = await response.text()
        
        assert.strictEqual( response.status, 200 )
        assert.ok( typeof text === 'string' )
        // Text format should be newline-separated country codes
    } )

    test( 'returns countries in text format with names when format=text&type=name', async () => {
        const response = await fetch( `${ BASE_URL }/api/lease/countries?format=text&type=name` )
        const text = await response.text()
        
        assert.strictEqual( response.status, 200 )
        assert.ok( typeof text === 'string' )
        // Text format should be newline-separated country names
    } )

    test( 'returns 500 when format is invalid', async () => {
        const { response, data } = await json.get( `${ BASE_URL }/api/lease/countries?format=xml` )
        
        assert.strictEqual( response.status, 500 )
        assert.ok( data && typeof data === 'object' )
        assert.ok( typeof data.error === 'string' && data.error.includes( 'Invalid format' ) )
    } )

    test( 'returns 500 when type is invalid', async () => {
        const { response, data } = await json.get( `${ BASE_URL }/api/lease/countries?type=invalid` )
        
        assert.strictEqual( response.status, 500 )
        assert.ok( data && typeof data === 'object' )
        assert.ok( typeof data.error === 'string' && data.error.includes( 'Invalid type' ) )
    } )

    test( 'supports both /api/lease/countries and /api/config/countries endpoints', async () => {
        const { response: response1, data: data1 } = await json.get( `${ BASE_URL }/api/lease/countries` )
        const { response: response2, data: data2 } = await json.get( `${ BASE_URL }/api/config/countries` )
        
        assert.strictEqual( response1.status, 200 )
        assert.strictEqual( response2.status, 200 )
        assert.deepStrictEqual( data1, data2 ) // Both endpoints should return the same data
    } )

} )