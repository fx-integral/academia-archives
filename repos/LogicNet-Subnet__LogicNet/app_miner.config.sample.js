module.exports = {
    apps : [{
      name   : 'your_miner_name', // update this name
      script : 'neurons/miner/miner.py',
      interpreter:  '/root/miniconda3/envs/sn35-env/bin/python', // update this path
      min_uptime: '5m',
      max_restarts: '5',
      env: {
        PYTHONPATH: './:${PYTHONPATH}'
      },
      args: [
        '--netuid','35',
        '--wallet.name','your_wallet_name',
        '--wallet.hotkey','your_hotkey',
        '--subtensor.network','finney',
        '--miner.category','Logic',
        '--miner.epoch_volume','512',
        '--miner.llm_client.base_url','https://api.openai.com/v1',
        '--miner.llm_client.model','gpt-4o-mini',
        '--miner.llm_client.key','your_openai_key',
        '--logging.debug',
        '--axon.port','',
        '--axon.external_port','',
        '--axon.external_ip','',
        ]
    }]
  }
  