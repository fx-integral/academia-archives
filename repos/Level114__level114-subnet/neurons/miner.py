# The MIT License (MIT)
# Copyright © 2025 Level114 Team

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import requests
import sys
import argparse
import bittensor as bt
from typing import Optional


DEFAULT_COLLECTOR_URL = "https://collector.level114.io"


class MinecraftServerRegistration:
    """
    Simple Level114 miner that ONLY registers Minecraft server information 
    with collector-center-main and exits.
    
    No axon, no background processes, no validator serving.
    """

    def __init__(self, config):
        self.config = config
        
        # Initialize wallet for signature
        self.wallet = bt.wallet(
            name=config.wallet_name,
            hotkey=config.wallet_hotkey,
            path=config.wallet_path
        )
        self.collector_url = DEFAULT_COLLECTOR_URL

    def create_signature(self, message: str) -> str:
        """Create signature for message using wallet hotkey"""
        try:
            bt.logging.debug(f"Creating signature for message: {message}")
            bt.logging.debug(f"Using hotkey: {self.wallet.hotkey.ss58_address}")
            
            # Convert message to bytes
            message_bytes = message.encode('utf-8')
            
            # Sign the message using Bittensor wallet
            signature = self.wallet.hotkey.sign(message_bytes)
            
            # Convert to hex string (lowercase)
            signature_hex = signature.hex()
            bt.logging.debug(f"Generated signature: {signature_hex[:20]}...")
            
            return signature_hex
            
        except Exception as e:
            bt.logging.error(f"Error creating signature: {e}")
            bt.logging.error(f"Message was: {message}")
            bt.logging.error(f"Hotkey: {self.wallet.hotkey.ss58_address}")
            raise

    def perform_minecraft_action(self) -> bool:
        """Register or unregister Minecraft server with collector-center-main"""
        try:
            action = getattr(self.config, 'action', 'register').lower()
            if action not in {'register', 'unregister'}:
                bt.logging.error(f"Unsupported action: {action}")
                return False

            if action == 'register':
                bt.logging.info("🎮 Registering Minecraft server with collector-center-main...")
            else:
                bt.logging.info("🎮 Unregistering Minecraft server from collector-center-main...")
            
            # Get server details
            minecraft_hostname = getattr(self.config, 'minecraft_hostname', None)
            minecraft_port = getattr(self.config, 'minecraft_port', 25565)

            if not minecraft_hostname:
                bt.logging.error("Minecraft server hostname is required for registration")
                return False
            
            # Create registration message (format expected by collector-center-main)
            message_prefix = 'register' if action == 'register' else 'unregister'
            message = f"{message_prefix}:{minecraft_hostname}:{minecraft_port}"
            signature = self.create_signature(message)
            
            # Prepare registration data (matching collector-center-main expected format)
            registration_data = {
                "hostname": minecraft_hostname,
                "port": minecraft_port,
                "hotkey": self.wallet.hotkey.ss58_address,
                "signature": signature
            }
            
            # Make registration request to collector
            collector_url = self.collector_url
            if action == 'register':
                bt.logging.info(f"Registering Minecraft server at {minecraft_hostname}:{minecraft_port}")
            else:
                bt.logging.info(f"Unregistering Minecraft server at {minecraft_hostname}:{minecraft_port}")
            bt.logging.info(f"Collector URL: {collector_url}")
            
            endpoint = 'register' if action == 'register' else 'unregister'
            response = requests.post(
                f"{collector_url}/servers/{endpoint}",
                json=registration_data,
                timeout=30
            )
            
            if response.status_code == 200:
                try:
                    result = response.json()
                except ValueError:
                    result = {}

                if action == 'register':
                    server_data = result.get('server', {}) or {}
                    credentials_data = result.get('credentials', {}) or {}

                    server_id = server_data.get('id', 'unknown')
                    api_token = credentials_data.get('token', 'unknown')
                    key_id = server_data.get('key_id', 'unknown')
                    store_token = (
                        credentials_data.get('store_token')
                        or server_data.get('store_token')
                        or 'unknown'
                    )
                    resolved_hostname = minecraft_hostname or server_data.get('hostname')
                    resolved_hostname = resolved_hostname or 'unknown'

                    bt.logging.success("✅ Minecraft server registered successfully!")
                    bt.logging.info(f"🎯 Server ID: {server_id}")
                    bt.logging.info(f"🆔 Store Token: {store_token}")
                    bt.logging.info(f"🔑 API Token: {api_token[:20]}...")
                    bt.logging.info(f"🧭 Minecraft Hostname: {resolved_hostname}")
                    bt.logging.info(f"🚪 Minecraft Port: {minecraft_port}")
                    bt.logging.info(f"🔐 Hotkey: {self.wallet.hotkey.ss58_address}")

                    self._save_credentials(
                        server_id,
                        api_token,
                        key_id,
                        minecraft_port,
                        resolved_hostname,
                        store_token,
                    )
                else:
                    bt.logging.success("✅ Minecraft server unregistered successfully!")
                    bt.logging.info(f"🧭 Minecraft Hostname: {minecraft_hostname}")
                    bt.logging.info(f"🚪 Minecraft Port: {minecraft_port}")

                return True
            else:
                action_word = 'register' if action == 'register' else 'unregister'
                bt.logging.error(f"❌ Failed to {action_word} Minecraft server: {response.status_code}")
                bt.logging.error(f"Response: {response.text}")
                return False
                
        except Exception as e:
            action_word = 'register' if action == 'register' else 'unregister'
            bt.logging.error(f"❌ Error trying to {action_word} Minecraft server: {e}")
            return False

    def _save_credentials(
        self,
        server_id: str,
        api_token: str,
        key_id: str,
        minecraft_port: int,
        minecraft_hostname: Optional[str] = None,
        store_token: Optional[str] = None,
    ):
        """Save server credentials to file"""
        try:
            import os
            from datetime import datetime
            import re
            
            # Create credentials directory if it doesn't exist
            creds_dir = "credentials"
            if not os.path.exists(creds_dir):
                os.makedirs(creds_dir)
            
            # Create filename based on wallet and minecraft server
            wallet_name = getattr(self.config, 'wallet_name', 'unknown')
            hotkey_name = getattr(self.config, 'wallet_hotkey', 'unknown')
            hostname_value = (
                minecraft_hostname
                or getattr(self.config, 'minecraft_hostname', None)
                or 'unknown'
            )
            hostname_safe = re.sub(r'[^A-Za-z0-9_\-]+', '_', hostname_value)
            store_token_value = store_token or 'unknown'
            filename = f"{creds_dir}/minecraft_server_{wallet_name}_{hotkey_name}_{hostname_safe}.txt"

            # Prepare credentials content
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            credentials_content = f"""# Level114 Minecraft Server Credentials
# Generated on: {timestamp}
# 
# KEEP THIS FILE SECURE!
# This information is necessary for server management.

[Server Information]
Server ID: {server_id}
API Token: {api_token}
Key ID: {key_id}
Store Token: {store_token_value}
Minecraft Hostname: {hostname_value}
Minecraft Port: {minecraft_port}

[Wallet Information]
Wallet Name: {wallet_name}
Hotkey Name: {hotkey_name}
Hotkey Address: {self.wallet.hotkey.ss58_address}

[Collector Information]
Collector URL: {self.collector_url}
Registration Time: {timestamp}

# How to use these credentials:
# - Server ID: Unique identifier of the server in the system
# - API Token: Token for authentication with collector-center-main
# - Keep this information for future interactions with the system
"""
            
            # Write credentials to file
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(credentials_content)
            
            # Also create a simple JSON format for programmatic access
            import json
            json_filename = filename.replace('.txt', '.json')
            json_data = {
                "server_id": server_id,
                "api_token": api_token,
                "key_id": key_id,
                "store_token": store_token_value,
                "minecraft_hostname": hostname_value,
                "minecraft_port": minecraft_port,
                "wallet_name": wallet_name,
                "hotkey_name": hotkey_name,
                "hotkey_address": self.wallet.hotkey.ss58_address,
                "collector_url": self.collector_url,
                "registration_time": timestamp
            }
            
            with open(json_filename, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, indent=2, ensure_ascii=False)
            
            bt.logging.success(f"💾 Credentials saved to files:")
            bt.logging.info(f"   📄 Text format: {filename}")
            bt.logging.info(f"   🔧 JSON format: {json_filename}")
            bt.logging.warning(f"⚠️  IMPORTANT: Keep these files secure!")
            
        except Exception as e:
            bt.logging.error(f"❌ Error saving credentials: {e}")
            bt.logging.warning("Credentials were not saved to file, but registration was successful")


def main():
    """Main entry point - register Minecraft server and exit"""
    
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Level114 Minecraft Server Registration')
    
    # Wallet arguments
    parser.add_argument('--wallet.name', dest='wallet_name', type=str, required=True, help='Wallet name')
    parser.add_argument('--wallet.hotkey', dest='wallet_hotkey', type=str, required=True, help='Wallet hotkey')
    parser.add_argument('--wallet.path', dest='wallet_path', type=str, default='~/.bittensor/wallets/', help='Wallet path')
    
    # Minecraft server arguments
    parser.add_argument('--minecraft_hostname', type=str, required=True, help='Minecraft server hostname (e.g., play.myserver.com)')
    parser.add_argument('--minecraft_port', type=int, default=25565, help='Minecraft server port (default: 25565)')
    parser.add_argument('--action', type=str, default='register', choices=['register', 'unregister'], help='Action to perform: register or unregister (default: register)')
    
    # Logging
    parser.add_argument('--logging.debug', action='store_true', dest='debug', help='Enable debug logging')
    
    args = parser.parse_args()
    
    # Set up logging
    if args.debug:
        bt.logging.set_debug(True)
    
    action = args.action.lower()
    action_title = 'Registration' if action == 'register' else 'Unregistration'

    bt.logging.info(f"🚀 Starting Level114 Minecraft Server {action_title}")
    bt.logging.info(f"Wallet: {args.wallet_name}.{args.wallet_hotkey}")
    bt.logging.info(f"Collector: {DEFAULT_COLLECTOR_URL}")
    if getattr(args, 'minecraft_hostname', None):
        bt.logging.info(f"Hostname: {args.minecraft_hostname}")

    try:
        # Create registration client
        registrar = MinecraftServerRegistration(args)

        # Register Minecraft server
        if registrar.perform_minecraft_action():
            if action == 'register':
                bt.logging.success("🎉 Registration completed successfully!")
                bt.logging.info("💡 Your Minecraft server is now registered with collector-center-main")
                bt.logging.info("")
                bt.logging.info("🔍 Check the 'credentials/' folder for your server credentials:")
                bt.logging.info(f"   📁 credentials/minecraft_server_{args.wallet_name}_{args.wallet_hotkey}_*.txt")
                bt.logging.info(f"   📁 credentials/minecraft_server_{args.wallet_name}_{args.wallet_hotkey}_*.json")
                bt.logging.info("")
                bt.logging.warning("⚠️  IMPORTANT: Keep the credentials files secure!")
                bt.logging.warning("   They contain Server ID and API Token necessary for server management.")
            else:
                bt.logging.success("🎉 Unregistration completed successfully!")
                bt.logging.info("💡 Your Minecraft server is no longer registered with collector-center-main")
            sys.exit(0)
        else:
            if action == 'register':
                bt.logging.error("❌ Registration failed!")
            else:
                bt.logging.error("❌ Unregistration failed!")
            sys.exit(1)

    except KeyboardInterrupt:
        if action == 'register':
            bt.logging.info("👋 Registration cancelled by user")
        else:
            bt.logging.info("👋 Unregistration cancelled by user")
        sys.exit(1)
    except Exception as e:
        if action == 'register':
            bt.logging.error(f"❌ Registration error: {e}")
        else:
            bt.logging.error(f"❌ Unregistration error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
