from setuptools import find_packages, setup

setup(
    name="wahoo",
    version="1.0.0",
    packages=find_packages(exclude=("tests",)),
    install_requires=[
        "bittensor>=7.0.0",
        "httpx>=0.25.0",
        "torch>=2.0.0",
        "python-dotenv>=1.0.0",
        "pandas>=2.0.0",
        "numpy>=1.26.0",
        "alembic>=1.13.0",
        "sqlalchemy>=2.0.0",
    ],
    python_requires=">=3.10",
)
