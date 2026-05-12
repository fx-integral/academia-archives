import os
import httpx
import hashlib
from typing import List
from datetime import datetime
from utils import logger

def get_gist(github_account: str, gist_id: str) -> str:
    raw_url = f"https://gist.githubusercontent.com/{github_account}/{gist_id}/raw"
    with httpx.Client(follow_redirects=True) as client:
        response = client.get(raw_url, timeout=60.0)
        if response.status_code == 200:
            content = response.text
            return content
        else:
            logger.error(f"Failed to download Gist from {raw_url}: {response.status_code} - {response.reason_phrase}")
            raise Exception(f"Failed to download Gist: {response.status_code} - {response.reason_phrase}")

def get_gist_created_at(gist_id: str) -> datetime:
    api_url = f"https://api.github.com/gists/{gist_id}"
    try:
        with httpx.Client() as client:
            response = client.get(api_url, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            created_at_str = data.get('created_at')
            if created_at_str:
                return datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
            else:
                raise ValueError("created_at field not found in Gist metadata")
    except Exception as e:        
        logger.error(f"Error fetching Gist metadata from {api_url}: {e}")
        raise

def get_gist_file_names(gist_id: str) -> List[str]:
    api_url = f"https://api.github.com/gists/{gist_id}"
    try:
        with httpx.Client() as client:
            response = client.get(api_url, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            files = data.get('files', {})
            file_names = list(files.keys())
            return file_names
    except Exception as e:        
        logger.error(f"Error fetching Gist metadata from {api_url}: {e}")
        raise

def get_gist_sha_commits(gist_id: str) -> List[str]:
    api_url = f"https://api.github.com/gists/{gist_id}/commits"
    try:
        with httpx.Client() as client:
            response = client.get(api_url, timeout=60.0)
            response.raise_for_status()
            commits = response.json()
            sha_list = [commit.get('version') for commit in commits if 'version' in commit]
            return sha_list
    except Exception as e:
        logger.error(f"Error fetching Gist commits from {api_url}: {e}")
        raise

def get_gist_hash(github_account: str, gist_id: str) -> str:
    content = get_gist(github_account, gist_id)
    return hashlib.sha256(content.encode('utf-8')).hexdigest()