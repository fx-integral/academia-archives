import os
import subprocess


def get_git_info():
    build_sha = os.getenv('BUILD_SHA')
    if build_sha:
        branch = 'main'
        sha = build_sha
    else:
        # Fallback to local git (for local development)
        try:
            branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], text=True).strip()
            if not branch:
                branch = 'detached'
        except subprocess.CalledProcessError:
            branch = 'unknown'
        
        try:
            sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        except subprocess.CalledProcessError:
            sha = 'unknown'
    
    return branch, sha

def get_git_sha():
    branch, sha = get_git_info()
    return sha

COMMIT_HASH = get_git_sha()