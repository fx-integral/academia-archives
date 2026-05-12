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
