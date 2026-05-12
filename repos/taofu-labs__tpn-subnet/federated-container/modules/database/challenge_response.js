import { log } from "mentie"
import { get_pg_pool } from "./postgres.js"

/**
 * Writes a challenge/solution pair to the database.
 * @param {Object} params - Parameters for writing a challenge/solution pair
 * @param {string} params.challenge - The challenge to write.
 * @param {string} params.solution - The solution to write.
 * @returns {Promise<{ success: boolean, challenge: string, solution: string }>} The result of the write operation.
 */
export async function write_challenge_solution_pair( { challenge, solution } ) {

    const pool = await get_pg_pool()

    const query = `
        INSERT INTO challenge_solution (challenge, solution, updated)
        VALUES ($1, $2, $3)
        ON CONFLICT (challenge) DO UPDATE SET solution = $2, updated = $3
    `

    try {

        await pool.query( query, [ challenge, solution, Date.now() ] )
        return { success: true, challenge, solution }

    } catch ( e ) {
        log.error( `Failed to write challenge/solution pair:`, e )
        throw new Error( `Failed to write challenge/solution pair: ${ e.message }` )
    }

}

/**
 * 
 * @param {Object} params - Parameters for retrieving a challenge solution
 * @param {string} params.challenge - The challenge for which to retrieve the solution.
 * @returns {Promise<{ success: boolean, challenge: string, solution?: string }>} The solution for the challenge, or an error if not found.
 */
export async function read_challenge_solution( { challenge } ) {

    const pool = await get_pg_pool()

    const query = `
        SELECT solution FROM challenge_solution WHERE challenge = $1
    `

    try {
        const result = await pool.query( query, [ challenge ] )
        if( result.rows.length === 0 ) return { success: false, challenge }

        return result.rows[0].solution

    } catch ( e ) {
        log.error( `Failed to get challenge/solution pair:`, e )
        throw new Error( `Failed to get challenge/solution pair: ${ e.message }` )
    }
}
