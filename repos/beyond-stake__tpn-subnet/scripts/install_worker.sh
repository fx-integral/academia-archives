#!/bin/bash
set -euo pipefail

# Ask for mining pool and payment setup information, skip ones that are already set in the environment
echo "Setting up a TPN Worker Node"
echo "---------------------------------"

# Prompt for Mining Pool URL and Payment Addresses if not set
if [ -z "${MINING_POOL_URL:-}" ]; then
    echo "To join a mining pool, please provide the mining pool URL (e.g., http://mining.pool.ip:3000)."
    echo "If you don't want to join a pool, just leave it blank and press Enter."
    read -p "Mining Pool URL: " MINING_POOL_URL
    echo ""
else
    echo "Using provided Mining Pool URL: $MINING_POOL_URL"
fi

# Prompt for Payment Addresses if not set
if [ -z "${PAYMENT_ADDRESS_EVM:-}" ]; then
    echo "Please provide your EVM payment address (for Ethereum-based payments)."
    echo "If you don't have one or don't want to set it up now, just leave it blank and press Enter."
    read -p "EVM Payment Address: " PAYMENT_ADDRESS_EVM
    echo ""
else
    echo "Using provided EVM Payment Address: $PAYMENT_ADDRESS_EVM"
fi

# Prompt for Bittensor Payment Address if not set
if [ -z "${PAYMENT_ADDRESS_BITTENSOR:-}" ]; then
    echo "Please provide your Bittensor payment address."
    echo "If you don't have one or don't want to set it up now, just leave it blank and press Enter."
    read -p "Bittensor Payment Address: " PAYMENT_ADDRESS_BITTENSOR
    echo ""
else
    echo "Using provided Bittensor Payment Address: $PAYMENT_ADDRESS_BITTENSOR"
fi
echo "Thank you! Proceeding with the installation..."


# Get the public IP address
SERVER_PUBLIC_HOST=$(curl -4 -s ipv4.icanhazip.com)
if [ -z "$SERVER_PUBLIC_HOST" ]; then
    SERVER_PUBLIC_HOST=$(curl -4 -s ifconfig.me) 
fi
if [ -z "$SERVER_PUBLIC_HOST" ]; then
    SERVER_PUBLIC_HOST=$(curl -4 -s api.ipify.org)
fi
if [ -z "$SERVER_PUBLIC_HOST" ]; then
    echo "Error: Unable to determine public IP address. Please check your internet connection."
    exit 1
fi
echo "Detected public IP address: $SERVER_PUBLIC_HOST"

# Wait for package lock
while fuser /var/{lib/{dpkg,apt/lists},cache/apt/archives}/lock >/dev/null 2>&1; do
	echo "Another package script is running, waiting for it to exit..."
	sleep 10
done


# Install the required system dependencies
sudo apt update
sudo apt install -y git jq

# Install docker
if ! command -v docker &> /dev/null; then
    echo "Docker not found, installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
else
    echo "Docker is already installed, skipping installation."
fi
# Install wireguard and wireguard-tools, these are commonly preinstalled on Ubuntu
sudo apt install -y wireguard wireguard-tools
sudo modprobe wireguard

# Clone the TPN repository, it contains all the required code
cd ~
git clone https://github.com/taofu-labs/tpn-subnet.git || echo "TPN repository already cloned, skipping."
# Add the current user to docker for rootless docker running
if [ -z "$USER" ]; then
    USER=$(whoami)
fi
echo "Adding user $USER to docker group for rootless docker usage."
sudo groupadd docker &> /dev/null || true
echo "User $USER added to docker group."
sudo usermod -aG docker $USER
echo "You may need to log out and log back in for the group changes to take effect."
newgrp docker << EOF

    # Set up .env
    echo "Setting up .env file for the worker node."
    cp ~/tpn-subnet/federated-container/.env.worker.example ~/tpn-subnet/federated-container/.env

    # Delete lines starting with SERVER_PUBLIC_HOST, PAYMENT_ADDRESS_EVM, PAYMENT_ADDRESS_BITTENSOR, MINING_POOL_URL
    sed -i '/^SERVER_PUBLIC_HOST=/d' ~/tpn-subnet/federated-container/.env
    sed -i '/^PAYMENT_ADDRESS_EVM=/d' ~/tpn-subnet/federated-container/.env
    sed -i '/^PAYMENT_ADDRESS_BITTENSOR=/d' ~/tpn-subnet/federated-container/.env
    sed -i '/^MINING_POOL_URL=/d' ~/tpn-subnet/federated-container/.env

    # Append the new values to the .env file
    echo "Appending configuration to .env file."
    {
        echo "SERVER_PUBLIC_HOST=$SERVER_PUBLIC_HOST"
        echo "PAYMENT_ADDRESS_EVM=$PAYMENT_ADDRESS_EVM"
        echo "PAYMENT_ADDRESS_BITTENSOR=$PAYMENT_ADDRESS_BITTENSOR"
        echo "MINING_POOL_URL=$MINING_POOL_URL"
    } >> ~/tpn-subnet/federated-container/.env

    # Start docker service
    echo "Starting Docker service."
    sudo service docker start

    # Run the update script to set up the worker node
    echo "Running the update script to set up the worker node."
    bash ~/tpn-subnet/scripts/update_node.sh

EOF

