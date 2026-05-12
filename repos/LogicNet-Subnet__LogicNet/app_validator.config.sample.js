module.exports = {
  apps: [{
    name: "sn35-validator", // update this name
    script: "neurons/validator/validator.py",
    interpreter: "/root/miniconda3/envs/sn35-env/bin/python", // update this path
    env: {
        APP_NAME: "sn35-validator",
        PYTHONPATH: './:${PYTHONPATH}',
        OPENAI_API_KEY: "your_openai_key",
        USE_TORCH: 1,
        VALIDATOR_USERNAME: "datapool_username",
        VALIDATOR_PASSWORD: "datapool_password",
        TASK_POOL_URL: "server_datapool_endpoint",
        MINIO_ENDPOINT: "minio_endpoint",
        MINIO_ACCESS_KEY: "minio_access_key",
        MINIO_SECRET_KEY: "minio_secret_key",
        PM2_LOG_DIR: "/root/.pm2/logs/"
    },
    args: [
        "--netuid", "35",
        "--wallet.name", "your_wallet_name",
        "--wallet.hotkey", "your_hotkey",
        "--subtensor.network", "finney",
        "--neuron_type", "validator",
        "--llm_client.gpt_url", "https://api.openai.com/v1",
        "--llm_client.gpt_model", "gpt-4o-mini",
        "--llm_client.vllm_url", "your_vllm_endpoint",
        "--llm_client.vllm_model", "your_vllm_model_name",
        "--llm_client.vllm_key", "your_vllm_key",
        "--logging.debug",
        "--batch_size", "8",
        "--batch_number", "8",
        "--loop_base_time", "600",
    ],
    autorestart: true,
  }]
};
