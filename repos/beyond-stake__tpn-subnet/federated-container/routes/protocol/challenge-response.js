import { Router } from "express"
import { cache, log, make_retryable } from "mentie"
import { cooldown_in_s, retry_times } from "../../modules/networking/routing.js"
import { request_is_local } from "../../modules/networking/network.js"
import { read_challenge_solution } from "../../modules/database/challenge_response.js"
import { generate_challenge } from "../../modules/scoring/challenge_response.js"
import { base_url } from "../../modules/networking/url.js"

export const router = Router()

router.get( '/new', async ( req, res ) => {

    const handle_route = async () => {


        // Allow only localhost to call this route
        if( !request_is_local( req ) ) return res.status( 403 ).json( { error: `Request not from localhost` } )

        // Get miner uid from get query
        const { miner_uid } = req.query
        const { challenge, challenge_url } = await generate_challenge( { tag: miner_uid } ) 

        return { challenge, challenge_url }
    
    }

    try {
        const retryable_handler = await make_retryable( handle_route, { retry_times, cooldown_in_s } )
        const response_data = await retryable_handler()
        return res.json( response_data )
    } catch ( error ) {
        return res.status( 500 ).json( { error: `Error handling new challenge route: ${ error.message }` } )
    }
} )

router.get( "/:challenge", async ( req, res ) => {


    const handle_route = async () => {


        const { challenge } = req.params
        const caller = request_is_local( req ) ? 'local' : 'remote'
    
        const cached_solution = cache( `challenge_solution_${ challenge }` )
        if( cached_solution ) {
            log.info( `[GET] Returning cached value to ${ caller } (no response provided) for challenge ${ challenge }: `, cached_solution )
            return  { response: cached_solution }
        }

        // Get the solution
        const solution = await read_challenge_solution( { challenge } )
        if( !cached_solution && solution ) cache( `challenge_solution_${ challenge }`, solution )

        // Formulate solution verification url
        let verification_url = new URL( base_url )
        verification_url.pathname = `/protocol/challenge/${ challenge }/${ solution }`
        log.info( `[GET] Returning challenge solution to ${ caller } (no response provided) for challenge ${ challenge }: `, solution )
        return { challenge, solution, verification_url }

    }

    try {

        const retryable_handler = await make_retryable( handle_route, { retry_times, cooldown_in_s } )
        const response_data = await retryable_handler()

        return res.json( response_data )

    } catch ( error ) {
        return res.status( 500 ).json( { error: `Error handling challenge/response route: ${ error.message }` } )
    }

} )

router.get( "/:challenge/:submitted_solution", async ( req, res ) => {


    const handle_route = async () => {



        const { challenge, submitted_solution } = req.params
        const caller = request_is_local( req ) ? 'local' : 'remote'
    
        const cached_solution = cache( `challenge_solution_${ challenge }` )
        const solution = cached_solution || await read_challenge_solution( { challenge } )
        if( !cached_solution && solution ) cache( `challenge_solution_${ challenge }`, solution )
        const correct = solution === submitted_solution

        log.info( `[GET] Returning challenge verification result to ${ caller } for challenge ${ challenge }: `, { correct } )
        return { correct }

    }

    try {

        const retryable_handler = await make_retryable( handle_route, { retry_times, cooldown_in_s } )
        const response_data = await retryable_handler()

        return res.json( response_data )

    } catch ( error ) {
        return res.status( 500 ).json( { error: `Error handling challenge/response route: ${ error.message }` } )
    }

} )