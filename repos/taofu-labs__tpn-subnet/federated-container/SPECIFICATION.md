# TPN Federated Network Specification

The federated version of TPN fundamentally changes how we operate. We will have 3 kinds of nodes in the network:

- [ ] Validators - these are validators in the Bittensor network and set the emission weigts
- [ ] Mining pools - these are miners in the Bittensor network and allow workers to serve config files
- [ ] Workers - these are off-chain nodes that offer VPN config files to the TPN network trough mining pools

These nodes will be controlled through the same codebase to make it easier to share code and deploy docker images. Much of the code can be recycled after refactoring.

## Shared specification

The TPN stack consists of the following basic container configuration

- [x] `tpn-federated` container
- [x] `lscr.io/linuxserver/swag` reverse proxy container
- [x] `postgres` database container
- [x] `watchtower` update checker
- [x] `willfarrell/autoheal` container restarter 

### `tpn-federated` shared endpoints

- [x] `POST /protocol/broadcast/neurons`
  - [x] Receive neuron data so we are aware of all validators and miners in the network (worker exempt)
- [x] `GET /protocol/stats`
  - [x] Returns TPN cache for debugging and visibility
- [x] `GET /`
  - [x] Health endpoint that returns current versions and uptime info

### `tpn-federated` shared environment variables

- [x] `LOG_LEVEL` *optional* - info, warn, error
- [x] `POSTGRES_HOST` *optional* - postgres host
- [x] `POSTGRES_USER` *optional* - postgres user
- [x] `POSTGRES_PASSWORD` *optional* - postgres password
- [x] `NODE_OPTIONS` - runtime configs

### Docker networks

- [x] `tpn-internal` - a network that has internal connectivity only and cannot reach the internet not be reached from it
- [x] `tpn-external` - which will only contain the reverse proxy server

Note that the network ip subnets will be set explicitly (manually with a default) so we can deterministically detect local requests in the TPN container.

----------------------------------------------------------------------------------------------------

## Validator specification

The validator checks the mining pool performance by asking it for worker configs, and then checking the quality of those connections. It does so by asking for the full worker list of a mining pool, and then selecting a random sample of workers whose performance is used to create a scoring of the mining pool.

### Validator responsibilities

- [ ] Periodically query mining pools for their full worker list and checking a random sample for uptime, make sure it only queries workers whose last submitted status was up so as to not punish pools for workers that are known to be down
  - [ ] The sample size is determined by [Cochranes formula](https://en.wikipedia.org/wiki/Cochran%27s_theorem)
  - [ ] The up status of a worker is verified by asking a worker to open a challenge/response endpoint on the validator itself
- [ ] Score mining pools based on their performance metrics
  - [ ] Reward the mean uniqueness score times the amount of workers, where each worker is scored as x% unique based on the network topology
  - [ ] Give a score boost to mining pools that have locked capital in an EVM contract, where:
  - [ ] `score = min( 100, score * ( 1 + boost/100 ) )`
  - [ ] `boost = max( boost ceiling - stake rank, 0 )`
  - [ ] `stake rank` is a simple ranking of the mining pools according to the amount staked in the contract
  - [ ] `boost ceiling` is the maximum amount of boost, probably in the range of 10-20
- [ ] Serve consumers with worker config files based on their input parameters

```js
// Cochranes formula calculates the sample size 'n'. With this sample size, we can be 'uptime_confidence_fraction' confident that our *measured* uptime from the sample will be within 'error_margin' of the *true* uptime of the entire node population.
// e.g. using 'n' would mean that we are 99% sure that the uptime we are measuring from the sample is within 5% of the real uptime
function sample_size( { uptime_confidence_fraction=.99, expected_proportion_up=.99, error_margin=.05, node_count } ) {

    const { jStat } = await import( 'jstat' )
    const alpha = 1 - uptime_confidence_fraction
    const cumulative_probability = 1 - alpha / 2
    const z_score = jStat.normal.inv( cumulative_probability, 0, 1 )

    // We can implement some pool based uptime history to streamline the formula
    if( !expected_proportion_up ) expected_proportion_up = moving_average_of_estimated_pool_up_fraction()

    const sample_size = ( z_score**2 * expected_proportion_up * ( 1- expected_proportion_up ) ) / error_margin**2

    // Do a finite population correction
    const fpc_sample_size = sample_size / ( 1 + ( ( sample_size - 1 ) / node_count ) )

    return Math.ceil( fpc_sample_size )

}
```

### Validator endpoints

- [x] `POST /validator/broadcast/workers/`
  - [x] Allows mining pools to submit their current workers. This may be done at any time by the mining pool (including faster than the cochrane query by the validator)
- [ ] `GET /api/lease/new?lease_seconds=100&format=text|json&geo=netherlands|NL&whitelist=1.1.1.1,2.2.2.2&blacklist=3.3.3.3`
  - [ ] Get a config, similar to what the mining pools expose, but with logic to select the best miner for the query
- [ ] `GET /api/countries?format=json|text&type=code|name`
  - [ ] All countries based on merged list of mining pool

### Validator environment variables

- [ ] `SERVER_PROTOCOL` - the protocol at which the validator should be called
- [ ] `SERVER_PUBLIC_URL` - the public url at which the validator can be reached on the internet
- [ ] `SERVER_PUBLIC_PORT` - the port at which the public url should be called
- [ ] `MAXMIND_LICENSE_KEY` - maxmind license key
- [ ] `IP2LOCATION_DOWNLOAD_TOKEN` - ip2location token

----------------------------------------------------------------------------------------------------

## Mining pool specification

The mining pool keeps track of all workers that are registered to it. Periodically it checks which are online, and in which country they are.

### Mining pool responsibilities

- [ ] Register incoming workers
  - [ ] Check if they offer valid connections
  - [ ] Check what country they are in
- [ ] Periodically call all workers to see if they are online
- [ ] Respond to validator requests for the worker list
- [ ] Provide the validator work config files
  - [ ] Validators may request with whitelist (and thus specific workers through a single item in whitelist)
  - [ ] Validators may request with blacklist

### Mining pool endpoints

- [ ] `GET /api/lease/new?lease_seconds=100&format=text|json&geo=netherlands|NL&whitelist=1.1.1.1,2.2.2.2&blacklist=3.3.3.3`
  - [ ] Validators may call this only. Retreives a config file with those parameters.
- [ ] `GET /api/countries?format=json|text&type=code|name`
  - [ ] All countries b
### Mining pool environment variables

- [ ] `SERVER_PROTOCOL` - the protocol at which the pool should be called
- [ ] `SERVER_PUBLIC_URL` - the public url at which the mining pool can be reached on the internet
- [ ] `SERVER_PUBLIC_PORT` - the port at which the public url should be called
- [ ] `MAXMIND_LICENSE_KEY` - maxmind license key
- [ ] `IP2LOCATION_DOWNLOAD_TOKEN` - ip2location token
- [ ] `MINING_POOL_WEBSITE_URL` - the url where worker managers can see the terms of this mining pool
- [ ] `MINING_POOL_REWARDS` - a short message describing how this mining pool pays the workers

----------------------------------------------------------------------------------------------------

## Worker specification

The worker registers itself with a TPN mining pool and then serves config files when that mining pool requests config files.

Additional containers in the worker:

- [ ] `taofuprotocol/wireguard` wireguard container, potentially multiple so as to have multiple ip subnet ranges and redundant containers available

### Worker responsibilities

- [ ] Register itself with mining pools by `ip`, `UID`, or `auto`
- [ ] Offer up config files when the chosen mining pool requests

### Worker endpoints

- [ ] `GET /worker/config/new?lease_seconds=Number`

### Worker environment variables

- [ ] `MINING_POOL` - may be an ipv4, a uid (int), or the string 'auto'
- [ ] `PAYMENT_ADDRESS_EVM` *optional* - is an EVM compatible payment address
- [ ] `PAYMENT_ADDRESS_BITTENSOR` *optional* - is a Bittensor address to receive payments on
- [ ] `BROADCAST_MESSAGE` *optional* - is an arbitraty string that will be returned on the `/` endpoint
- [ ] `CONTACT_METHOD` *optional* - is any contact method in case the mining pool wants to contact a miner
