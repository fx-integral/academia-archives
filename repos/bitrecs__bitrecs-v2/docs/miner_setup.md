# Mining on Bitrecs

Mining on this subnet is done via submitting an artifact for evaluation. These artifacts are simple yaml files (prompts and parameters) that the system will test against a suite of evaluations.

Please read our [submission policy](artifact_policy.md) to understand the rules of the system.

The steps for a miner are:

- aquire fresh hotkey from subnet
- create an artifact.yaml
- test and tune artifact.yaml locally
- upload artifact to https://gist.github.com/ 
- take gist_id and run this command:

```
uv run bitrecs_cli.py upload --github-account mygithubaccount --gist-id your_gist_id --coldkey-name default --hotkey-name default
```
**Note: submitting an artifact can take up to 1 minute**

## Eval Process

Once your artifact has been uploaded it will go into an evaluation queue. This queue consists of 2 screeners and n validators. Each screener runs a specific set of basic evals to ensure data consistency. Once your artifact reaches the validator queue, it will be evalauted against a rotating set of evals to measure performance. Each validator computes the WTA miner and sets weights accordingly.

## Miner Setup

Install UV

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```
Clone repo
```
git clone repo
```
Sync and Setup Environment
```
uv sync
```
Create environment file
```
touch .env
SUBTENSOR_ADDRESS=wss://test.finney.opentensor.ai:443
SUBTENSOR_NETWORK=test
```

Submit artifact
```
uv run bitrecs_cli.py upload --github-account mygithubaccount --gist-id your_gist_id --coldkey-name default --hotkey-name default
```

## General Mining Tips

- Only 1 submission per hotkey
- The system only accepts gists that have a single commit. So if you create a gist, then go back to edit it - it will be rejected by the system.
- Gists submitted must be < 24 hours old
- View example [miner_artifact.yml](../miner/miner_artifact.yaml) to see how variables are used 

### Gist Artifact Fields

| Field    | Note | Required |
| -------- | ------- | ------- |
| name  | your unique artifact description    | Yes
| version_num | must be "1"     | Yes
| status    | must be "screening_1"    | Yes
| miner_hotkey    | your miner hotkey    | Yes
| provider    | only CHUTES or OPEN_ROUTER permitted    | Yes
| model    | any supported model < $1/m tokens    | Yes
| system_prompt_template    | your system prompt    | Yes
| user_prompt_template    | your user prompt    | Yes
| sampling_params    | temperature is only param used    | Yes

