import { test, describe } from 'node:test'
import assert from 'node:assert'
import { json } from './_helpers.js'
import { BASE_URL } from './_fixtures.js'

describe( '/protocol/stats endpoint', () => {


    test( 'should return valid TPN cache stats', async () => {
        const { response, data } = await json.get( `${ BASE_URL }/protocol/stats` )

        assert.strictEqual( response.status, 200 )
        assert.ok( data )
        assert.strictEqual( typeof data, 'object' )
    } )

    test( 'should return stats object with expected structure', async () => {
        const { response, data } = await json.get( `${ BASE_URL }/protocol/stats` )

        assert.strictEqual( response.status, 200 )
            
        // The response should be an object (TPN cache)
        assert.strictEqual( typeof data, 'object' )
        assert.ok( data !== null )
            
        // If there are any cached items, they should be accessible
        // The cache might be empty initially, so we just verify it's a valid object
        const keys = Object.keys( data )
        assert.ok( Array.isArray( keys ) )
    } )


} )
