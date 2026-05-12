#!/usr/bin/env python3
import argparse
import subprocess
import time
import os

REPO_DIR = os.getcwd()  # Use current directory only
CHECK_INTERVAL = 300    # Check interval in seconds
PM2_NAME = "sn116-validator"

def run_cmd(cmd, cwd=None):
    """Run command and return output"""
    result = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print(f"Command failed: {' '.join(cmd)}")
        print(result.stderr)
    return result.stdout.strip()

def get_latest_tag():
    """Get latest remote tag"""
    run_cmd(["git", "fetch", "--tags"], cwd=REPO_DIR)
    tags = run_cmd(["git", "tag", "--sort=-creatordate"], cwd=REPO_DIR).splitlines()
    if not tags:
        return None
    return tags[0]  # Latest tag

def get_current_tag():
    """Get current checked out tag. Return None if no tag exists."""
    tag = run_cmd(["git", "describe", "--tags", "--abbrev=0"], cwd=REPO_DIR)
    if not tag:
        return None
    return tag

def upgrade_validator(pm2_name):
    """Update to latest tag and build"""
    latest_tag = get_latest_tag()
    current_tag = get_current_tag()
    print(f"latest_tag: {latest_tag}, current_tag: {current_tag}")

    if latest_tag != None and latest_tag != current_tag:
        print(f"New version found: {latest_tag}, current version: {current_tag}")
        # Force switch to the latest tag, discarding local changes
        run_cmd(["git", "reset", "--hard"], cwd=REPO_DIR)
        run_cmd(["git", "checkout", "-f", latest_tag], cwd=REPO_DIR)

        # Restart pm2
        print(f"🔄 Restarting {pm2_name} ...")
        subprocess.run(["pm2", "restart", pm2_name], check=True)
        print(f"✅ {pm2_name} restarted successfully")

    else:
        print(f"Already at latest version: {current_tag}")

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="Automatically update and restart the validator process when a new version is released.",
        epilog="Example usage: python start_validator.py --pm2_name 'sn116-validator' --wallet.name 'wallet1' --wallet.hotkey 'key1'",
    )

    parser.add_argument(
        "--pm2_name", default=PM2_NAME, help="Name of the PM2 process."
    )

    flags, extra_args = parser.parse_known_args()

    # Start validator
    # Check if pm2 process exists, if so, delete it first
    try:
        pm2_list = subprocess.run(["pm2", "list"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if flags.pm2_name in pm2_list.stdout:
            print(f"Detected existing pm2 process: {flags.pm2_name}, deleting...")
            subprocess.run(["pm2", "delete", flags.pm2_name], check=False)
    except Exception as e:
        print(f"Error checking pm2 process: {e}")

    # Start validator
    print(f"Starting validator process: {flags.pm2_name}")
    subprocess.run(["pm2", "start", "--name", flags.pm2_name, "python3", "--", "neurons/validator.py", *extra_args], check=False)

    while True:
        try:
            upgrade_validator(flags.pm2_name)
        except Exception as e:
            print(f"Script error: {e}")
        time.sleep(CHECK_INTERVAL)