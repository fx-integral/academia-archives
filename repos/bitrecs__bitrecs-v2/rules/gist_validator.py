from typing import Tuple
from datetime import datetime, timedelta, timezone
from utils.gist import get_gist_created_at, get_gist_sha_commits

def validate_artifact_gist(gist_id: str) -> Tuple[bool, str]:
    if len(gist_id) == 0:
        return False, "gist_id must not be empty"
    
    gist_created_at = get_gist_created_at(gist_id)
    now = datetime.now(timezone.utc)
    if gist_created_at > now:
        return False, "Gist created_at timestamp is in the future - please check the Gist creation time and ensure it is correct"

    if gist_created_at < now - timedelta(hours=24):
        return False, "Gist must be created within the last 24 hours"

    #only accept single commit gist
    commits = get_gist_sha_commits(gist_id)
    if len(commits) != 1:
        return False, "Gist must not have multiple commits - please create a new Gist for each submission and do not update the Gist after submission"

    return True, ""
