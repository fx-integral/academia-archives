import os
import asyncio
import docker
import utils.logger as logger
from pathlib import Path
from typing import List


EVAL_CONTAINER_TAG = "ghcr.io/bitrecs/bitrecs-evals:main"

async def get_eval_container_sha() -> str:
    try:
        client = docker.from_env()  # Connects via /var/run/docker.sock by default
        image = client.images.get(EVAL_CONTAINER_TAG)
        sha = image.labels.get("org.opencontainers.image.revision", "unknown")
        return sha
    except docker.errors.DockerException as e:
        logger.warning(f"Docker API not accessible (likely not in DinD or socket not mounted): {e}")
        return "unknown"
    except Exception as e:
        logger.warning(f"Unexpected error in get_eval_container_sha(): {e}")
        return "unknown"


async def get_eval_container_sha_subprocess() -> str:
    try:
        command = f'docker inspect {EVAL_CONTAINER_TAG} | jq -r \'.[0].Config.Labels["org.opencontainers.image.revision"]\''
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            sha = stdout.decode().strip()
            return sha if sha else "unknown"
        else:
            logger.warning(f"Command failed: {stderr.decode()}")
            return "unknown"
    except Exception as e:
        logger.warning(f"Unexpected error in get_eval_container_sha_subprocess(): {e}")
        return "unknown"


async def get_num_docker_containers() -> int:
    """
    Get the number of running Docker containers using the Docker API.  
    """
    try:
        client = docker.from_env()  # Connects via /var/run/docker.sock by default
        containers = client.containers.list()
        return len(containers)
    except docker.errors.DockerException as e:
        logger.warning(f"Docker API not accessible (likely not in DinD or socket not mounted): {e}")
        return 0
    except Exception as e:
        logger.warning(f"Unexpected error in get_num_docker_containers(): {e}")
        return 0
    

async def list_all_docker_containers() -> List[dict]:
    """
    List all running Docker containers with their metadata using the Docker API.
    """
    try:
        client = docker.from_env()  # Connects via /var/run/docker.sock by default
        containers = client.containers.list()
        container_info = []
        for container in containers:
            image_tag = container.image.tags[0] if container.image.tags else container.image.id
            info = {
                'name': container.name,
                'image': image_tag,
                'status': container.status,
                'id': container.short_id,
                'created': container.attrs.get('Created', 'Unknown')
            }
            container_info.append(info)
        if not container_info:
            logger.warning("No running Docker containers found.")
        return container_info
    except docker.errors.DockerException as e:
        logger.warning(f"Docker API not accessible (likely not in DinD or socket not mounted): {e}")
        return []
    except Exception as e:
        logger.warning(f"Unexpected error in list_all_docker_containers(): {e}")
        return []


def is_running_in_container() -> bool:
    """
    Cross-platform container detection with caching for performance.
    """
    # 1. Classic .dockerenv marker
    if Path('/.dockerenv').exists():
        return True

    # 2. Podman / buildah / recent runtimes
    if Path('/run/.containerenv').exists():
        return True

    # 3. Cgroup-based detection
    cgroup_path = Path('/proc/1/cgroup')
    if cgroup_path.exists():
        try:
            content = cgroup_path.read_text(encoding='utf-8', errors='ignore')
            keywords = ['docker', 'kubepods', 'containerd', 'cri-o', 'libpod']
            if any(kw in content for kw in keywords):
                return True
            # Cgroup v2: Check for container-like paths or depth
            lines = content.splitlines()
            for line in lines:
                parts = line.strip().split(':', 2)
                if len(parts) == 3:
                    _, _, path = parts
                    if path != '/' and any(c in path.lower() for c in keywords):
                        return True
                    if len([p for p in path.split('/') if p]) >= 3:
                        return True
        except Exception:
            pass

    # 4. PID namespace check
    try:
        if os.stat('/proc/1/ns/pid').st_ino != os.stat('/proc/self/ns/pid').st_ino:
            return True
    except Exception:
        pass

    return False