import { log } from "mentie"
import { get_pg_pool } from "./postgres.js"

/**
 * Write mining pool metadata to db
 * @param {Object} params - Input parameters.
 * @param {string} params.mining_pool_uid - Unique identifier of the mining pool.
 * @param {string} params.mining_pool_ip - IP address of the mining pool.
 * @param {string} params.protocol - Protocol used by the mining pool (e.g. http, https)
 * @param {string} params.url - URL of the mining pool.
 * @param {number} params.port - Port number of the mining pool.
 * @returns {Promise<{ success: boolean, mining_pool_uid: string, mining_pool_ip: string, protocol: string, url: string, port: number }>} - The result of the database operation.
 * @throws {Error} If the Postgres pool is unavailable or if the database query fails.
 */
export async function write_mining_pool_metadata( { mining_pool_uid, mining_pool_ip, protocol, url, port } ) {

    // Get the postgres pool
    const pool = await get_pg_pool()

    // Create query
    const query = `
        INSERT INTO mining_pool_metadata_broadcast (mining_pool_uid, mining_pool_ip, protocol, url, port, updated)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (mining_pool_uid, mining_pool_ip) DO UPDATE
        SET protocol = $3, url = $4, port = $5, updated = $6
    `
    
    try {

        await pool.query( query, [ mining_pool_uid, mining_pool_ip, protocol, url, port, Date.now() ] )
        log.info( `Wrote mining pool metadata for ${ mining_pool_uid }@${ mining_pool_ip }: `, { mining_pool_uid, mining_pool_ip, protocol, url, port } )
        return { success: true, mining_pool_uid, mining_pool_ip, protocol, url, port }


    } catch ( e ) {
        log.error( `Error writing mining pool metadata: ${ e.message }` )
        throw new Error( `Error writing mining pool metadata: ${ e.message }` )
    }
}

/**
 * Reads mining pool metadata for a given pool UID and IP address from Postgres.
 * @param {Object} params - Parameters for the metadata lookup.
 * @param {string} params.mining_pool_uid - Unique identifier of the mining pool.
 * @param {string} params.mining_pool_ip - IPv4/IPv6 address of the mining pool.
 * @param {number} [params.limit=1] - Maximum number of records to retrieve.
 * @returns {Promise<
 *   | { success: false, message: string }
 *   | { success: true } & Record<string, any>
 *   | { success: true, pools: Array<Record<string, any>> }
 * >} Resolves to an object indicating success and either the mining pool metadata or an error message.
 * @throws {Error} If the Postgres pool is unavailable or if the database query fails.
 */
export async function read_mining_pool_metadata( { mining_pool_uid, mining_pool_ip, limit=1 } ) {

    // Get the postgres pool
    const pool = await get_pg_pool()

    // Dynamic wheres depending on params
    const wheres = []
    const values = []
    if( mining_pool_uid ) {
        values.push( mining_pool_uid )
        wheres.push( `mining_pool_uid = $${ values.length }` )
    }
    if( mining_pool_ip ) {
        values.push( mining_pool_ip )
        wheres.push( `mining_pool_ip = $${ values.length }` )
    }

    // Add limit to values
    if( limit > 0 ) values.push( limit )

    // Create query
    const query = `
        SELECT * FROM mining_pool_metadata_broadcast
        ${ wheres.length > 0 ? `WHERE ${ wheres.join( ' AND ' ) }` : '' }
        ${ limit > 0 ? `LIMIT $${ values.length }` : '' }
    `

    try {
        const result = await pool.query( query, values )
        if( result.rows.length === 0 ) {
            log.warn( `No mining pool metadata found for ${ mining_pool_uid }@${ mining_pool_ip }` )
            return { success: false, message: `No mining pool metadata found` }
        }
        log.debug( `Read mining pool metadata for ${ mining_pool_uid }@${ mining_pool_ip }` )
        return { success: true, ...limit == 1 ? result.rows[0] : { pools: result.rows } }
    } catch ( e ) {
        log.error( `Error reading mining pool metadata: ${ e.message }`, { wheres, values } )
        throw new Error( `Error reading mining pool metadata: ${ e.message }` )
    }
}

export async function write_pool_score( { mining_pool_ip, mining_pool_uid, stability_score, size_score, performance_score, geo_score, score } ) {

    // Get postgres pool
    const pool = await get_pg_pool()

    // Formulate insert (not update) query
    const query = `
        INSERT INTO scores (mining_pool_ip, mining_pool_uid, stability_score, size_score, performance_score, geo_score, score, updated)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (mining_pool_ip, mining_pool_uid) DO UPDATE
        SET stability_score = $3, size_score = $4, performance_score = $5, geo_score = $6, score = $7, updated = $8
    `

    try {
        await pool.query( query, [ mining_pool_ip, mining_pool_uid, stability_score, size_score, performance_score, geo_score, score, Date.now() ] )
        log.info( `Wrote pool score for ${ mining_pool_uid }@${ mining_pool_ip }` )
        return { success: true, mining_pool_ip, mining_pool_uid, stability_score, size_score, performance_score, geo_score, score }
    } catch ( e ) {
        log.error( `Error writing pool score: ${ e.message }` )
        throw new Error( `Error writing pool score: ${ e.message }` )
    }
}

export async function get_pool_scores() {

    // Get postgres pool
    const pool = await get_pg_pool()

    // Create query
    const query = `
        SELECT * FROM scores
        ORDER BY score DESC
    `

    try {
        const result = await pool.query( query )
        log.debug( `Retrieved ${ result.rows.length } pool scores` )
        return { success: true, scores: result.rows }
    } catch ( e ) {
        log.error( `Error retrieving pool scores: ${ e.message }` )
        return { success: false, message: `Error retrieving pool scores: ${ e.message }` }
    }

}