from setuptools import setup, find_packages

setup(
    name="merit",
    version="1.0",
    packages=find_packages(where="merit"),
    package_dir={"": "merit"},
    install_requires=[
        "bittensor",
        "pyotp",
    ],
    entry_points={
        "console_scripts": [
            "run_miner=merit.scripts.run_miner:main",
            "run_validator=merit.scripts.run_validator:main",
        ],
    },
)

