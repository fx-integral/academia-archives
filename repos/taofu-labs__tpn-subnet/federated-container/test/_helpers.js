// Test helpers for HTTP requests

/**
 * Core fetch helper that handles both JSON and non-JSON responses
 * @param {string} url - The URL to fetch
 * @param {Object} options - Fetch options (method, body, etc.)
 * @returns {Object} - Object with response, data, and error handling
 */
async function fetch_json_core( url, options = {} ) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json'
        },
        ...options
    }

    try {
        const response = await fetch( url, defaultOptions )
        
        // Clone the response so we can read it multiple times
        const clonedResponse = response.clone()
        
        try {
            // Try to parse as JSON
            const data = await response.json()
            return { response: clonedResponse, data, success: true }
        } catch ( jsonError ) {
            // If JSON parsing fails, get text and log it
            const text = await clonedResponse.text()
            console.log( `Non-JSON response from ${ url }:`, text )
            return { 
                response: clonedResponse, 
                data: null, 
                text, 
                success: false,
                error: 'Response is not valid JSON'
            }
        }
    } catch ( fetchError ) {
        console.log( `Fetch error for ${ url }:`, fetchError.message )
        return { 
            response: null, 
            data: null, 
            success: false,
            error: fetchError.message 
        }
    }
}

/**
 * Convenient JSON API wrapper
 */
export const json = {
    /**
     * GET request
     * @param {string} url - The URL to fetch
     * @param {Object} options - Additional fetch options (headers, etc.)
     * @returns {Object} - Object with response, data, and error handling
     */
    get: ( url, options = {} ) => {
        return fetch_json_core( url, { method: 'GET', ...options } )
    },

    /**
     * POST request
     * @param {string} url - The URL to fetch
     * @param {Object} data - Data to send in the request body (will be JSON.stringify'd)
     * @param {Object} options - Additional fetch options (headers, etc.)
     * @returns {Object} - Object with response, data, and error handling
     */
    post: ( url, data = {}, options = {} ) => {
        return fetch_json_core( url, { 
            method: 'POST', 
            body: JSON.stringify( data ),
            ...options 
        } )
    },

    /**
     * PUT request
     * @param {string} url - The URL to fetch
     * @param {Object} data - Data to send in the request body (will be JSON.stringify'd)
     * @param {Object} options - Additional fetch options (headers, etc.)
     * @returns {Object} - Object with response, data, and error handling
     */
    put: ( url, data = {}, options = {} ) => {
        return fetch_json_core( url, { 
            method: 'PUT', 
            body: JSON.stringify( data ),
            ...options 
        } )
    },

    /**
     * DELETE request
     * @param {string} url - The URL to fetch
     * @param {Object} options - Additional fetch options (headers, etc.)
     * @returns {Object} - Object with response, data, and error handling
     */
    delete: ( url, options = {} ) => {
        return fetch_json_core( url, { method: 'DELETE', ...options } )
    }
}

// Keep the old fetch_json for backward compatibility
export const fetch_json = json.post
