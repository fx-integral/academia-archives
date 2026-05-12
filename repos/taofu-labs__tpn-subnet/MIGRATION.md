# Migration instructions for legacy nodes

This file is only relevant for those that ran a validator or miner before TPN deployed the federated network upgrade.

## Step 1: down your running services

```bash
# Stop all docker containers
docker stop $(docker ps -a -q)
# Stop all pm2 processes
pm2 stop all
```

## Step 2: Pull all changes

```bash
cd tpn-subnet
git pull
docker compose -f federated-container/docker-compose.yml pull
```

## Step 3: update your configuration

You may now read the `README.md` file and follow the instructions for your miner/validator.


> [!NOTE]
> A LOT CHANGED FOR MINERS. You MUST pay close attenton to configuring your .env file, if you misconfigure it nothing will work. If you have questions, ask us for help in Discord.

YOU MAY SKIP:

- the host-level package installations (`apt update` and so forth), running these again has no negative consequences
- wallet key setup, we recommend you keep your existing keys meaning you skip the wallet/key sections of the `README.md`

## Step 4: verify your setup

Once your machine is up and running, you should check if everything is up and running. Before you do so, make sure you go through this checklist:

- [ ] `docker compose -f federated-container/docker-compose.yml ps` shows running containers
- [ ] `pm2 list` shows your running neuron
- [ ] Your logs show your machine is ready when you run `docker compose -f federated-container/docker-compose.yml logs -f`
  - [ ] NO lines saying maxmind updates are `still running`, this takes a while the first time you start your node
  - [ ] NO lines indicating errors in your configuration (scroll to the top)

## Step 5: clean up old data

You may clean old docker files once your new setup is up and running. This will clear up disk space used by docker resources you no longer need.

You may clear up unused resources by running:

```bash
docker system prune -a --volumes
```