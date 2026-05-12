import os
import pytest
from dotenv import load_dotenv
load_dotenv()
from utils.database import initialize_database, deinitialize_database

@pytest.fixture(scope="function")
async def db_setup():
    """Initialize database for each test and clean up after."""
    await initialize_database(
        username=os.getenv("DATABASE_USERNAME"),
        password=os.getenv("DATABASE_PASSWORD"),
        host=os.getenv("DATABASE_HOST"),
        port=int(os.getenv("DATABASE_PORT", 5432)),
        name=os.getenv("DATABASE_NAME")
    )
    yield
    await deinitialize_database()