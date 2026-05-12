from pathlib import Path
root_path = Path(__file__).parent.absolute()
from utils.git import get_git_info

if __name__ == '__main__':
    branch, sha = get_git_info()
    version_file_path = "/tmp/version.txt"
    with open(version_file_path, 'w') as f:
        f.write(f"{branch}\n{sha}\n")
    print(f"Version written: branch={branch}, sha={sha}")