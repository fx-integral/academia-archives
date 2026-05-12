from setuptools import setup, find_packages

setup(
    name="merit",
    version="1.0",
    packages=find_packages(),
    install_requires=[
        "bittensor",
        "pyotp",
    ],
    entry_points={
        "console_scripts": [
            "run_miner=scripts.run_miner:main",
            "run_validator=scripts.run_validator:main",
        ],
    },
)

