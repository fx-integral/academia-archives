import { log } from "mentie"
import { get_pg_pool } from "./postgres.js"

/**
 * Get a timestamp value for a given label.
 * @param {Object} params - The parameters object
 * @param {string} params.label - The label for the timestamp
 * @returns {Promise<number>} - The timestamp value for the label, or 0 if not found
 * @throws {Error} - If the label is invalid or if there is an error retrieving the timestamp
 */
export async function get_timestamp( { label } ) {

    // Validate input
    if( typeof label !== 'string' || !label ) throw new Error( 'Invalid label' )

    // Get the postgres pool
    const pool = await get_pg_pool()

    // Retrieve the timestamp for the given label
    const result = await pool.query(
        `SELECT timestamp FROM timestamps WHERE label = $1 LIMIT 1`,
        [ label ]
    )
    return result.rows.length > 0 ? result.rows[0].timestamp : 0
}

/**
 * Set a timestamp for a given label
 * @param {Object} params - The parameters object
 * @param {string} params.label - The label for the timestamp
 * @param {number} params.timestamp - The timestamp value to set
 * @returns {Promise<Object>} - The result object containing the label and timestamp
 * @throws {Error} - If the label or timestamp is invalid, or if there is
 */
export async function set_timestamp( { label, timestamp } ) {

    // Validate input
    if( typeof label !== 'string' || !label ) throw new Error( 'Invalid label' )
    if( typeof timestamp !== 'number' || isNaN( timestamp ) ) throw new Error( 'Invalid timestamp' )

    // Get the postgres pool
    const pool = await get_pg_pool()

    // Insert or update the timestamp record
    await pool.query(
        `INSERT INTO timestamps (label, timestamp, updated) VALUES ($1, $2, $3)
        ON CONFLICT (label)
        DO UPDATE SET timestamp = $4, updated = $5`,
        [ label, timestamp, Date.now(), timestamp, Date.now() ]
    )
    log.debug( 'Timestamp set:', { label, timestamp } )

    return { label, timestamp }
}