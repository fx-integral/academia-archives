# The MIT License (MIT)
# Copyright © 2026 TAO Colosseum

import re
from setuptools import setup, find_packages


def get_version():
    """Read VERSION from const.py without importing the package."""
    with open("taocolosseum/core/const.py") as f:
        match = re.search(r'VERSION\s*=\s*"([^"]+)"', f.read())
    if not match:
        raise RuntimeError("VERSION not found in taocolosseum/core/const.py")
    return match.group(1)


setup(
    name="taocolosseum",
    version=get_version(),
    description="TAO Colosseum - P2P betting on Bittensor EVM with validator incentives",
    author="TAO Colosseum",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "setuptools>=70",
        "requests>=2",
        "bittensor>=9.11",
        "web3>=6.0.0",
        "eth-account>=0.10.0",
        "fastapi>=0.100.0",
        "uvicorn>=0.23.0",
        "substrate-interface",
    ],
    entry_points={
        "console_scripts": [
            "tao-colosseum-validator=validator.validator:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
