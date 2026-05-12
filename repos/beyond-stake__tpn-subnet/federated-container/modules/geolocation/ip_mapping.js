import { cache, is_ipv4, log, sanetise_ipv4 } from "mentie"
import { country_name_from_code, ip_geodata } from "./helpers.js"
import { set_tpn_cache, tpn_cache_keys } from "../caching.js"
const { CI_MODE } = process.env

/**
 * Map a list of IP addresses to their geolocation data
 * @param {Object} param - The input parameters
 * @param {Array} param.ips - The list of IP addresses to map
 * @param {Object} param.ip_to_uid - Optional mapping of IP addresses to UIDs (if known)
 * @param {string} param.cache_prefix - The cache prefix to use
 * @param {boolean} param.prefix_merge - Whether to merge the results with existing cache entries
 * @returns {Promise<{ ip_to_country: Object, country_count: Object, country_code_to_ips: Object, country_code_to_name: Object, country_name_to_code: Object, country_annotated_ips: Array }>} - The mapping of IP addresses to their geolocation data
 */
export async function map_ips_to_geodata( { ips=[], ip_to_uid={}, cache_prefix, prefix_merge=false } ) {

    // Sanetise input
    log.info( `Sanitising ${ ips.length } IP addresses`, ips[0] )
    ips = ips.map( ip => sanetise_ipv4( { ip } ) ).filter( is_ipv4 )
    ips = [ ...new Set( ips ) ]
    log.info( `Mapping ${ ips.length } unique ips to geodata with prefix ${ cache_prefix }` )
    if( cache_prefix ) cache_prefix = cache_prefix.replaceAll( '__', '_' )

    const country_annotated_ips = await Promise.all( ips.map( async ip_address => {
    
        try {

            const { country_code } = await ip_geodata( ip_address )
            if( !country_code ) throw new Error( `Cannot determine country of ip ${ ip_address }` )

            return { ip_address, country_code, uid: ip_to_uid[ ip_address ] || null }

        } catch ( e ) {

            if( CI_MODE !== 'true' ) log.warn( `Error looking up country_code for ip ${ ip_address }`, e )
            return { ip_address, country_code: 'unknown' }

        }
    
    } ) )

    // Reduce the ip array to a mapping of ips to country and uid
    const ip_to_country = country_annotated_ips.reduce( ( acc, { ip_address, country_code, uid } ) => {
        acc[ ip_address ] = { country_code, uid }
        return acc
    }, {} )


    // Reduce the ip array to a mapping of country to count
    const country_count = country_annotated_ips.reduce( ( acc, { country_code } ) => {
        if( !acc[ country_code ] ) acc[ country_code ] = 1
        else acc[ country_code ] += 1
        return acc
    } , {} )

    // Reduce the ip array to a mapping of country to ips
    const country_code_to_ips = country_annotated_ips.reduce( ( acc, { ip_address, country_code } ) => {
        if( !acc[ country_code ] ) acc[ country_code ] = []
        acc[ country_code ].push( ip_address )
        return acc
    }, {} )

    // Translate available country codes to full country names
    const country_codes = Object.keys( country_count )
    const country_code_to_name = country_codes.reduce( ( acc, code ) => {

        try {
            // Get the country name
            const name = country_name_from_code( code )
            if( !name ) return acc

            acc[ code ] = name
        } catch ( e ) {
            log.warn( `Error getting country name for code ${ code }`, e )
        }
            
        return acc

    }, {} )
    const country_name_to_code = country_codes.reduce( ( acc, code ) => {

        // Get country code
        const country_name = country_code_to_name[ code ]
        if( !country_name ) return acc
        acc[ country_name ] = code
        return acc

    }, {} )

    // Update cache to have this data
    log.info( `Updating TPN cache with geolocation data for ${ ips.length } ips` )
    set_tpn_cache( { key: `ip_to_country`, value: ip_to_country, merge: true } )
    set_tpn_cache( { key: `country_code_to_ips`, value: country_code_to_ips, merge: true } )
    set_tpn_cache( { key: `country_code_to_name`, value: country_code_to_name, merge: true } )
    set_tpn_cache( { key: `country_name_to_code`, value: country_name_to_code, merge: true } )
    set_tpn_cache( { key: 'country_count', value: country_count, merge: true } )
    set_tpn_cache( { key: 'ip_addresses', value: ips, merge: true } )

    // If cache prefix is set, add it to TPN cache or cache
    if( cache_prefix ) {

        log.info( `Updating TPN cache with prefix ${ cache_prefix } for ${ ips.length } ips` )

        let key = `${ cache_prefix }_ip_to_country`
        if( tpn_cache_keys.includes( key ) ) set_tpn_cache( { key, value: ip_to_country, merge: prefix_merge } )
        else cache( key, ip_to_country )

        key = `${ cache_prefix }_country_code_to_ips`
        if( tpn_cache_keys.includes( key ) ) set_tpn_cache( { key, value: country_code_to_ips, merge: prefix_merge } )
        else cache( key, country_code_to_ips )

        key = `${ cache_prefix }_country_code_to_name`
        if( tpn_cache_keys.includes( key ) ) set_tpn_cache( { key, value: country_code_to_name, merge: prefix_merge } )
        else cache( key, country_code_to_name )

        key = `${ cache_prefix }_country_name_to_code`
        if( tpn_cache_keys.includes( key ) ) set_tpn_cache( { key, value: country_name_to_code, merge: prefix_merge } )
        else cache( key, country_name_to_code )

        key = `${ cache_prefix }_country_count`
        if( tpn_cache_keys.includes( key ) ) set_tpn_cache( { key, value: country_count, merge: prefix_merge } )
        else cache( key, country_count )

        key = `${ cache_prefix }_ip_addresses`
        if( tpn_cache_keys.includes( key ) ) set_tpn_cache( { key, value: ips, merge: prefix_merge } )
        else cache( key, ips )

    }

    return {
        ip_to_country,
        country_count,
        country_code_to_ips,
        country_code_to_name,
        country_name_to_code,
        country_annotated_ips
    }

}