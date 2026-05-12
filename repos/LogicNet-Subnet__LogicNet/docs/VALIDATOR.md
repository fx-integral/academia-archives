# LogicNet: Validator Documentation

## Overview

The Validator is responsible for generating challenges for the Miner to solve. It evaluates solutions submitted by Miners and rewards them based on the quality and correctness of their answers. Additionally, it incorporates penalties for late responses.

**Protocol**: `LogicSynapse`

- **Validator Prepares**:
  - `raw_logic_question`: A math problem
  - `logic_question`: A personalized challenge created by refining `raw_logic_question` with an LLM.
- **Miner Receives**:
  - `logic_question`: The challenge to solve.
- **Miner Submits**:
  - `logic_reasoning`: Step-by-step reasoning to solve the challenge.
  - `logic_answer`: The final answer to the challenge, expressed as a short sentence.

### Reward Structure

- **Correctness (`bool`)**: Checks if `logic_answer` matches the ground truth.
- **Similarity (`float`)**: Measures cosine similarity between `logic_reasoning` and the Validator’s reasoning.
- **Time Penalty (`float`)**: Applies a penalty for delayed responses based on the formula:
  
  ```
  time_penalty = (process_time / timeout) * MAX_PENALTY
  ```

## Setup for Validator

Follow the steps below to configure and run the Validator.

### Step 1: Configure for vLLM

This setup allows you to run the Validator locally by hosting a vLLM server. While it requires significant resources, it offers full control over the environment.

#### Minimum Compute Requirements

- **GPU**: 1x GPU with 24GB VRAM (e.g., RTX 4090, A100, A6000)
- **Storage**: 300GB (minimum)
- **Python**: 3.10

#### Steps

1. **Set Up vLLM Environment**
   ```bash
   python -m venv vllm
   . vllm/bin/activate
   pip install vllm
   ```

2. **Install PM2 for Process Management**
   ```bash
   sudo apt update && sudo apt install jq npm -y
   sudo npm install pm2 -g
   pm2 update
   ```

3. **Select a Model**
   Supported models are listed [here](https://docs.vllm.ai/en/latest/models/supported_models.html).

4. **Start the vLLM Server**
   ```bash
   . vllm/bin/activate
   pm2 start "vllm serve Qwen/Qwen2.5-7B-Instruct --port 8000 --host 0.0.0.0" --name "sn35-vllm" --api-key your_vllm_key
   ```
   - If you want to run larger models on GPUs with less VRAM, there are several techniques you can use to optimize GPU memory utilization:
      - You can adjust the GPU memory utilization to maximize the available memory by using a flag like `--gpu_memory_utilization`. This allows the model to use a specified percentage of GPU memory.
      ```bash
      pm2 start "vllm serve Qwen/Qwen2.5-7B-Instruct --gpu_memory_utilization 0.95 --port 8000 --host 0.0.0.0" --name "sn35-vllm" --api-key your_vllm_key
      # This command sets the model to use 95% of the available GPU memory.
      ```
      - Using mixed precision (FP16) instead of full precision (FP32) reduces the amount of memory required to store model weights, which can significantly lower VRAM usage.
      ```bash
      pm2 start "vllm serve Qwen/Qwen2.5-7B-Instruct --precision fp16 --gpu_memory_utilization 0.95 --port 8000 --host 0.0.0.0" --name "sn35-vllm" --api-key your_vllm_key
      ```
      - If you have multiple GPUs, you can shard the model across them to distribute the memory load.
      ```bash
      pm2 start "vllm serve Qwen/Qwen2.5-7B-Instruct --shard --port 8000 --host 0.0.0.0" --name "sn35-vllm" --api-key your_vllm_key
      ```

---

### Step 2: Configure Open AI for cheat detection system

#### Prerequisites

- **OpenAI API Key**: Obtain from the OpenAI platform dashboard.
- **Python 3.10**
- **Node v23.3.0**
- **PM2 Process Manager**: For running and managing the Validator process. *OPTIONAL*

#### Steps

1. **Clone the Repository**
   ```bash
   git clone https://github.com/LogicNet-Subnet/LogicNet logicnet
   cd logicnet
   ```

2. **Delete pm2 log**
   
   PM2_LOG_DIR: directory of the PM2 logs on your machine, default is `/root/.pm2/logs`
   
   ```bash
   sudo rm -rf $PM2_LOG_DIR
   ```

3. **Install the Requirements**
   ```bash
   python -m venv main
   . main/bin/activate

   bash install.sh
   ```
   Alternatively, install manually:
   ```bash
   pip install -e .
   pip uninstall uvloop -y
   ```
4. **Run the validator code**

   4.1 **[Recommend] Option 1: Run pm2 by config file**
      - Create file `app_validator.config.js` base on `app_validator.config.sample.js`
      - Update `env` in `app_validator.config.js` by your information:
      ```bash
         # Need to change
         OPENAI_API_KEY: "your_openai_key",
         VALIDATOR_USERNAME: "datapool_username",
         VALIDATOR_PASSWORD: "datapool_password",
         TASK_POOL_URL: "server_datapool_endpoint",
         MINIO_ENDPOINT: "minio_endpoint",
         MINIO_ACCESS_KEY: "minio_access_key",
         MINIO_SECRET_KEY: "minio_secret_key",
         PM2_LOG_DIR: "/root/.pm2/logs/" # must be obsolute path

         # Can keep default
         APP_NAME: "sn35-validator",
         PYTHONPATH: './:${PYTHONPATH}',
         USE_TORCH: 1,
      ```
      - Update `args`:
      ```bash
         # Need to change
         "--wallet.name", "your_wallet_name",
         "--wallet.hotkey", "your_hotkey",
         "--llm_client.vllm_url", "your_vllm_endpoint",
         "--llm_client.vllm_model", "your_vllm_model_name",
         "--llm_client.vllm_key", "your_vllm_key",
         
         # Can keep default
         "--netuid", "35",
         "--subtensor.network", "finney",
         "--neuron_type", "validator",
         "--llm_client.gpt_url", "https://api.openai.com/v1",
         "--llm_client.gpt_model", "gpt-4o-mini",
         "--logging.debug",
         "--batch_size", "8",
         "--batch_number", "8",
         "--loop_base_time", "600",
      ```

   4.2 **Option 2: Run validator by pm2 command**

   - Set Up the `.env` File
      ```bash
      echo "OPENAI_API_KEY=your_openai_api_key" >> .env
      echo "TASK_POOL_URL=server_datapool_endpoint"
      echo "VALIDATOR_USERNAME=datapool_username" >> .env
      echo "VALIDATOR_PASSWORD=datapool_account" >> .env
      echo MINIO_ENDPOINT="server_minio_endpoint" >> .env
      echo MINIO_ACCESS_KEY="minio_username" >> .env
      echo MINIO_SECRET_KEY="minio_password" >> .env
      echo APP_NAME="sn35-validator" >> .env
      echo PM2_LOG_DIR: "pm2_log_dir/" >> .env
      echo "USE_TORCH=1" >> .env
      ```

   - Activate Virtual Environment**
      ```bash
      . main/bin/activate
      ```

   - Source the `.env` File**
      ```bash
      source .env
      ```

   - Start the Validator
      ```bash
      pm2 start python --name "sn35-validator" -- neurons/validator/validator.py \
         --netuid 35 \
         --wallet.name "your-wallet-name" \
         --wallet.hotkey "your-hotkey-name" \
         --subtensor.network finney \
         --neuron_type validator \
         --logging.debug
      ```

      > ***Optional Flags*** (incase you want to run the validator with different configurations)
      ```
         --llm_client.gpt_url https://api.openai.com/v1 \
         --llm_client.gpt_model gpt-4o-mini \

         --llm_client.vllm_url 0.0.0.0:8000/v1 \
         --llm_client.vllm_model Qwen/Qwen2.5-7B-Instruct \
         --llm_client.vllm_key xyz \ 
      ```

      Enable Public Access (Optional) *For recieving challenges from the frontend app*
      ```bash
      --axon.port "your-public-open-port"
      ```

### IMPORTANT NOTE
- Ensure APP_NAME in the .env file matches the PM2 app name exactly. This is important to ensure that you find the correct location for the log files and upload them to minio
- Make sure the PM2_LOG_DIR is correct with "ls $PM2_LOG_DIR
". The default is /root/.pm2/logs, but you may need to set a different value depending on your server. Verify carefully with your machine, set the path to absolute
- Delete old log files before rerunning the code to avoid issues from large files generated by old code version: rm -rf $PM2_LOG_DIR.
- Check the logs immediately after restarting to identify any issues with the code.

### Troubleshooting & Support

- **Logs**:
  - Please see the logs for more details using the following command.
  ```bash
  pm2 logs sn35-validator
  ```

- **Common Issues**:
  - Missing API keys.
  - Incorrect model IDs.
  - Connectivity problems.
- **Contact Support**: Reach out to the LogicNet team for assistance.

---

Happy Validating!
