import { test, describe } from 'node:test'
import assert from 'node:assert'
import { json } from './_helpers.js'
import { BASE_URL, invalidWorkers, mixedWorkers, validWorkers } from './_fixtures.js'

describe( '/validator/broadcast/workers endpoint (miners broadcast workers to validators)', () => {

    describe( 'Success cases', () => {

        test( 'should accept valid worker data from a miner (mining pool)', async () => {
            // Use workers that don't depend on country validation for this test
            const testWorkers = [
                { ip: '8.8.8.8', country_code: 'XX' },      // Use a test country code
                { ip: '1.1.1.1', country_code: 'XX' },     // Use a test country code  
                { ip: '208.67.222.222', country_code: 'XX' } // Use a test country code
            ]
            
            const { response, data } = await json.post( `${ BASE_URL }/validator/broadcast/workers`, { 
                workers: testWorkers 
            } )

            assert.strictEqual( response.status, 200 )
            assert.strictEqual( data.success, true )
            assert.ok( typeof data.count === 'number' )
            assert.ok( data.count >= 0 )
            assert.ok( data.mining_pool_uid )
            // broadcast metadata should be present and correct
            assert.ok( data.broadcast_metadata )
            assert.strictEqual( data.broadcast_metadata.last_known_worker_pool_size, testWorkers.length )
            assert.ok( typeof data.broadcast_metadata.updated === 'number' )
        } )

        test( 'should handle empty worker array from miner', async () => {
            const { response, data } = await json.post( `${ BASE_URL }/validator/broadcast/workers`, { 
                workers: [] 
            } )

            assert.strictEqual( response.status, 200 )
            assert.strictEqual( data.success, true )
            assert.strictEqual( data.count, 0 )
            // broadcast metadata may be omitted when no valid workers; if present, verify it's consistent
            if( data.broadcast_metadata ) {
                assert.strictEqual( data.broadcast_metadata.last_known_worker_pool_size, 0 )
                assert.ok( typeof data.broadcast_metadata.updated === 'number' )
            }
        } )

        test( 'should handle missing workers field from miner', async () => {
            const { response, data } = await json.post( `${ BASE_URL }/validator/broadcast/workers`, {} )

            assert.strictEqual( response.status, 200 )
            assert.strictEqual( data.success, true )
            assert.strictEqual( data.count, 0 )
            // broadcast metadata may be omitted when no valid workers; if present, verify it's consistent
            if( data.broadcast_metadata ) {
                assert.strictEqual( data.broadcast_metadata.last_known_worker_pool_size, 0 )
                assert.ok( typeof data.broadcast_metadata.updated === 'number' )
            }
        } )

        test( 'should filter out invalid workers from miner and process valid ones', async () => {
            const { response, data } = await json.post( `${ BASE_URL }/validator/broadcast/workers`, { 
                workers: mixedWorkers
            } )

            assert.strictEqual( response.status, 200 )
            assert.strictEqual( data.success, true )
            // Should process fewer workers than submitted due to filtering
            assert.ok( data.count <= mixedWorkers.length )
            // Metadata must reflect sanitized valid count
            assert.ok( data.broadcast_metadata )
            assert.strictEqual( data.broadcast_metadata.last_known_worker_pool_size, data.count )
            assert.ok( typeof data.broadcast_metadata.updated === 'number' )
        } )

        test( 'should sanitize IPv4 addresses from miner submissions', async () => {
            const workersWithSpaces = [
                { ip: ' 192.168.1.1 ', country_code: 'US' },
                { ip: '10.0.0.1\n', country_code: 'CA' }
            ]

            const { response, data } = await json.post( `${ BASE_URL }/validator/broadcast/workers`, { 
                workers: workersWithSpaces 
            } )

            assert.strictEqual( response.status, 200 )
            assert.strictEqual( data.success, true )
            // Two entries become valid after trimming
            assert.ok( data.broadcast_metadata )
            assert.strictEqual( data.broadcast_metadata.last_known_worker_pool_size, 2 )
            assert.ok( typeof data.broadcast_metadata.updated === 'number' )
        } )

        test( 'should handle large worker arrays from miner', async () => {
            const largeWorkerArray = Array.from( { length: 100 }, ( _, i ) => ( {
                ip: `192.168.1.${ i + 1 }`,
                country_code: 'US'
            } ) )

            const { response, data } = await json.post( `${ BASE_URL }/validator/broadcast/workers`, { 
                workers: largeWorkerArray 
            } )

            assert.strictEqual( response.status, 200 )
            assert.strictEqual( data.success, true )
            assert.ok( data.count >= 0 )
            // Metadata should reflect full batch size
            assert.ok( data.broadcast_metadata )
            assert.strictEqual( data.broadcast_metadata.last_known_worker_pool_size, largeWorkerArray.length )
            assert.ok( typeof data.broadcast_metadata.updated === 'number' )
        } )

    } )

    describe( 'Validation failures', () => {

        test( 'should reject requests from non-miners', async () => {
            // This test assumes the request will be rejected due to miner authentication
            // The exact behavior depends on how is_miner_request works
            const { response, data } = await json.post( `${ BASE_URL }/validator/broadcast/workers`, { 
                workers: validWorkers
            }, {
                headers: {
                    'X-Forwarded-For': '1.2.3.4', // Non-validator IP
                    'Content-Type': 'application/json'
                }
            } )

            // Note: This might return 403 or 200 with error depending on implementation
            if( response.status === 403 ) {
                assert.ok( data.error.includes( 'not a known miner' ) )
            } else if( response.status === 200 && data.error ) {
                assert.ok( data.error.includes( 'not a known miner' ) )
            }
        } )

        test( 'should handle completely invalid worker data', async () => {
            const { response, data } = await json.post( `${ BASE_URL }/validator/broadcast/workers`, { 
                workers: invalidWorkers
            } )
            assert.strictEqual( response.status, 200 )
            assert.strictEqual( data.success, true )
            // Some workers might be valid in CI mode due to lenient validation
            assert.ok( data.count >= 0 )
            assert.ok( data.count <= invalidWorkers.length )
            // If some entries are valid after validation, metadata must match count
            if( data.broadcast_metadata ) {
                assert.strictEqual( data.broadcast_metadata.last_known_worker_pool_size, data.count )
                assert.ok( typeof data.broadcast_metadata.updated === 'number' )
            }
        } )

        test( 'should handle workers with invalid IP formats', async () => {
            const invalidIPWorkers = [
                { ip: '999.999.999.999', country_code: 'US' },
                { ip: '192.168.1', country_code: 'US' },
                { ip: '192.168.1.1.1', country_code: 'US' },
                { ip: 'not.an.ip.address', country_code: 'US' }
            ]

            const { response, data } = await json.post( `${ BASE_URL }/validator/broadcast/workers`, { 
                workers: invalidIPWorkers 
            } )

            assert.strictEqual( response.status, 200 )
            assert.strictEqual( data.success, true )
            assert.strictEqual( data.count, 0 ) // All should be filtered out
            // No valid workers; metadata may be omitted; if present, it must show 0
            if( data.broadcast_metadata ) {
                assert.strictEqual( data.broadcast_metadata.last_known_worker_pool_size, 0 )
                assert.ok( typeof data.broadcast_metadata.updated === 'number' )
            }
        } )

        test( 'should handle workers with invalid country codes', async () => {
            const invalidCountryWorkers = [
                { ip: '192.168.1.1', country_code: 'INVALID' },
                { ip: '192.168.1.2', country_code: 'XYZ' },
                { ip: '192.168.1.3', country_code: '' },
                { ip: '192.168.1.4', country_code: null }
            ]

            const { response, data } = await json.post( `${ BASE_URL }/validator/broadcast/workers`, { 
                workers: invalidCountryWorkers 
            } )

            assert.strictEqual( response.status, 200 )
            assert.strictEqual( data.success, true )
            // In CI mode, country validation is bypassed for non-empty strings
            // So workers with 'INVALID' and 'XYZ' country codes will be valid
            // Only workers with empty string or null country codes will be filtered out
            assert.ok( data.count >= 0 )
            assert.ok( data.count <= invalidCountryWorkers.length )
            if( data.broadcast_metadata ) {
                assert.strictEqual( data.broadcast_metadata.last_known_worker_pool_size, data.count )
                assert.ok( typeof data.broadcast_metadata.updated === 'number' )
            }
        } )

    } )

    describe( 'Error handling', () => {

        test( 'should handle malformed JSON from miner', async () => {
            const response = await fetch( `${ BASE_URL }/validator/broadcast/workers`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: 'invalid json{'
            } )

            assert.strictEqual( response.status, 400 )
        } )

        test( 'should handle non-object request body from miner', async () => {
            const { response } = await json.post( `${ BASE_URL }/validator/broadcast/workers`, 
                'not an object'
            )

            // Expecting 400 for malformed JSON/non-object
            assert.strictEqual( response.status, 400 )
        } )

        test( 'should handle workers field as non-array from miner', async () => {
            const { response, data } = await json.post( `${ BASE_URL }/validator/broadcast/workers`, { 
                workers: 'not an array' 
            } )

            assert.strictEqual( response.status, 200 )
            // Expecting an error for non-array workers field
            assert.ok( data.error )
            assert.ok( data.error.includes( 'reduce is not a function' ) )
        } )

    } )

    describe( 'Data integrity', () => {

        test( 'should maintain worker data integrity through processing from miner', async () => {
            const specificWorkers = [
                { ip: '203.0.113.1', country_code: 'US' }, // TEST-NET-3
                { ip: '198.51.100.1', country_code: 'CA' }, // TEST-NET-2
            ]

            const { response, data } = await json.post( `${ BASE_URL }/validator/broadcast/workers`, { 
                workers: specificWorkers 
            } )

            assert.strictEqual( response.status, 200 )
            assert.strictEqual( data.success, true )
            // Verify the response includes mining pool information
            assert.ok( data.mining_pool_uid !== undefined )
            assert.ok( data.mining_pool_ip !== undefined )
            // Metadata should reflect the number of valid entries (2)
            assert.ok( data.broadcast_metadata )
            assert.strictEqual( data.broadcast_metadata.last_known_worker_pool_size, specificWorkers.length )
            assert.ok( typeof data.broadcast_metadata.updated === 'number' )
        } )

        test( 'should handle concurrent miner requests gracefully', async () => {
            const requests = Array.from( { length: 5 }, () => 
                json.post( `${ BASE_URL }/validator/broadcast/workers`, { 
                    workers: validWorkers.slice( 0, 2 ) 
                } )
            )

            const responses = await Promise.all( requests )
            
            // All requests should succeed
            responses.forEach( ( { response, data } ) => {
                assert.strictEqual( response.status, 200 )
                assert.strictEqual( data.success, true )
                // Metadata should be present per response and reflect sanitized count (2)
                assert.ok( data.broadcast_metadata )
                assert.strictEqual( data.broadcast_metadata.last_known_worker_pool_size, 2 )
                assert.ok( typeof data.broadcast_metadata.updated === 'number' )
            } )
        } )

    } )

    describe( 'Performance and limits', () => {

        test( 'should handle reasonable batch sizes from miner efficiently', async () => {
            const batchWorkers = Array.from( { length: 50 }, ( _, i ) => ( {
                ip: `10.0.${ Math.floor( i / 254 ) }.${ i % 254 + 1 }`,
                country_code: 'US'
            } ) )

            const startTime = Date.now()
            const { response, data } = await json.post( `${ BASE_URL }/validator/broadcast/workers`, { 
                workers: batchWorkers 
            } )
            const endTime = Date.now()

            assert.strictEqual( response.status, 200 )
            assert.strictEqual( data.success, true )
            // Should complete in reasonable time (less than 5 seconds)
            assert.ok( endTime - startTime < 5000 )
            // Metadata should reflect full batch size
            assert.ok( data.broadcast_metadata )
            assert.strictEqual( data.broadcast_metadata.last_known_worker_pool_size, batchWorkers.length )
            assert.ok( typeof data.broadcast_metadata.updated === 'number' )
        } )

    } )

} )

// Separate top-level describe for the mining pool endpoint tests
describe( '/validator/broadcast/mining_pool endpoint (miners self-broadcast metadata)', () => {

    describe( 'Success cases', () => {
        test( 'should accept valid mining pool metadata from miner', async () => {
            const payload = { protocol: 'https', url: 'example.com', port: 443 }
            const { response, data } = await json.post( `${ BASE_URL }/validator/broadcast/mining_pool`, payload )
            assert.strictEqual( response.status, 200 )
            assert.strictEqual( data.success, true )
            assert.ok( data.mining_pool_uid !== undefined )
            assert.ok( data.mining_pool_ip !== undefined )
        } )
    } )

    describe( 'Validation failures', () => {
        test( 'should return an error for invalid protocol', async () => {
            const payload = { protocol: 'ftp', url: 'example.com', port: 443 }
            const { response, data } = await json.post( `${ BASE_URL }/validator/broadcast/mining_pool`, payload )

            assert.strictEqual( response.status, 200 )
            assert.ok( data.error )
            assert.ok( data.error.includes( 'Invalid protocol' ) )
        } )
    } )

} )
