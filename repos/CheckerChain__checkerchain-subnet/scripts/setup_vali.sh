#!/bin/bash

if [ -z "$VIRTUAL_ENV" ]; then
    echo "Not inside a virtual environment."

    # Step 1: Check and create .venv
    if [ ! -d ".venv" ]; then
        echo "Creating virtual environment..."
        python3 -m venv .venv
    else
        echo ".venv already exists"
    fi

    # Step 2: Activate virtual environment
    echo "Activating virtual environment..."
    source .venv/bin/activate
else
    echo "Already inside a virtual environment: $VIRTUAL_ENV"
fi

# Step 3: Install package in editable mode
echo "Installing package in editable mode..."
pip install -e .

# Step 4: Check and create database file
DB_FILE="checker_db.db"

if [ -f "$DB_FILE" ]; then
    echo "Database file $DB_FILE already exists. Deleting..."
    rm "$DB_FILE"
fi

echo "Creating new database file $DB_FILE..."
touch "$DB_FILE"


# Step 5: Run Alembic migrations
echo "Running alembic migrations..."
alembic upgrade head
