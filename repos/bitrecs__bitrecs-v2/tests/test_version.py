from version import __version__

def test_version():
    assert __version__ == "2.1.0"


def test_get_get_info():
    from utils.git import get_git_info
    branch, sha = get_git_info()
    print(f"Branch: {branch}, SHA: {sha}")
    assert branch is not None
    assert sha is not None