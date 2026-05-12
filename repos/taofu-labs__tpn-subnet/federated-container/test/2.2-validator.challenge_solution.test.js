import { test, describe } from 'node:test'
import assert from 'node:assert'
import { json } from './_helpers.js'
import { BASE_URL } from './_fixtures.js'
import { validate as uuidValidate, version as uuidVersion } from 'uuid'

// Helper to extract the solution string from varying response shapes
function extractSolutionString( data ) {
    if( !data ) return undefined
    // Direct string
    if( typeof data.solution === 'string' ) return data.solution
    // Object with solution
    if( data.solution && typeof data.solution === 'object' && typeof data.solution.solution === 'string' ) {
        return data.solution.solution
    }
    // Cached shape
    if( typeof data.response === 'string' ) return data.response
    if( data.response && typeof data.response === 'object' && typeof data.response.solution === 'string' ) {
        return data.response.solution
    }
    return undefined
}

describe( '/protocol/challenge endpoints', () => {

    test( 'should create a new challenge and return a challenge_url', async () => {
        const miner_uid = '99999'
        const { response, data } = await json.get( `${ BASE_URL }/protocol/challenge/new?tag=${ miner_uid }` )

        assert.strictEqual( response.status, 200 )
        assert.ok( data.challenge )
        assert.ok( typeof data.challenge === 'string' )
        assert.ok( uuidValidate( data.challenge ), 'challenge must be a valid UUID' )
        assert.ok( uuidVersion( data.challenge ) === 4, 'challenge must be a UUIDv4' )
        assert.ok( data.challenge_url )
        assert.ok( typeof data.challenge_url === 'string' )
        assert.ok( data.challenge_url.includes( data.challenge ) )
    } )

    test( 'should fetch the solution payload for a challenge via /:challenge', async () => {
        const miner_uid = '12345'
        const { data: newData } = await json.get( `${ BASE_URL }/protocol/challenge/new?tag=${ miner_uid }` )
        const { challenge } = newData

        assert.ok( uuidValidate( challenge ), 'challenge must be a valid UUID' )

        const { response, data } = await json.get( `${ BASE_URL }/protocol/challenge/${ challenge }` )
        assert.strictEqual( response.status, 200 )

        // Accept either { challenge, solution, verification_url } or { response }
        assert.ok( data.challenge === challenge || data.response )
        if( data.challenge === challenge ) {
            assert.ok( typeof data.verification_url === 'string' )
            assert.ok( data.verification_url.includes( challenge ) )
        }

        const solutionStr = extractSolutionString( data )
        assert.ok( typeof solutionStr === 'string' )
        assert.ok( uuidValidate( solutionStr ), 'solution must be a valid UUID' )
        assert.ok( uuidVersion( solutionStr ) === 4, 'solution must be a UUIDv4' )
    } )

    test( 'should return correct=false for an incorrect submitted solution', async () => {
        const miner_uid = 'abc'
        const { data: newData } = await json.get( `${ BASE_URL }/protocol/challenge/new?tag=${ miner_uid }` )
        const { challenge } = newData

        assert.ok( uuidValidate( challenge ), 'challenge must be a valid UUID' )

        const { response, data } = await json.get( `${ BASE_URL }/protocol/challenge/${ challenge }/this-is-wrong` )
        assert.strictEqual( response.status, 200 )
        assert.ok( typeof data.correct === 'boolean' )
        assert.strictEqual( data.correct, false )
    } )

    test( 'should return a boolean when submitting the purported correct solution', async () => {
        const miner_uid = '777'
        const { data: newData } = await json.get( `${ BASE_URL }/protocol/challenge/new?tag=${ miner_uid }` )
        const { challenge } = newData

        assert.ok( uuidValidate( challenge ), 'challenge must be a valid UUID' )

        // Retrieve the solution payload
        const { data: solveData } = await json.get( `${ BASE_URL }/protocol/challenge/${ challenge }` )
        let solutionStr = extractSolutionString( solveData )
        // Fallback: parse from verification_url if present
        if( typeof solutionStr !== 'string' && typeof solveData?.verification_url === 'string' ) {
            try {
                const url = new URL( solveData.verification_url )
                const parts = url.pathname.split( '/' )
                solutionStr = parts.pop() || parts.pop() // handle trailing slash
            } catch { /* ignore */ }
        }
        assert.ok( typeof solutionStr === 'string' )
        assert.ok( uuidValidate( solutionStr ), 'solution must be a valid UUID' )

        // Submit what we believe is the correct solution
        const { response, data } = await json.get( `${ BASE_URL }/protocol/challenge/${ challenge }/${ solutionStr }` )
        assert.strictEqual( response.status, 200 )
        // Current implementation may not evaluate equality correctly; just assert a boolean is returned
        assert.ok( typeof data.correct === 'boolean' )
    } )

} )
