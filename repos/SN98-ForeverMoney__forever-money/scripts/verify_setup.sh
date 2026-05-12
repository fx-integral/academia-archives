#!/bin/bash
# Verification script for SN98 ForeverMoney setup

echo "======================================"
echo "SN98 ForeverMoney Setup Verification"
echo "======================================"
echo ""

# Check Python version
echo "1. Checking Python version..."
python_version=$(python3 --version 2>&1)
echo "   ✓ $python_version"
echo ""

# Check if dependencies are installed
echo "2. Checking Python dependencies..."
if python3 -c "import bittensor" 2>/dev/null; then
    echo "   ✓ bittensor installed"
else
    echo "   ✗ bittensor not installed (run: pip install -r requirements.txt)"
fi

if python3 -c "import flask" 2>/dev/null; then
    echo "   ✓ flask installed"
else
    echo "   ✗ flask not installed (run: pip install -r requirements.txt)"
fi

if python3 -c "import pydantic" 2>/dev/null; then
    echo "   ✓ pydantic installed"
else
    echo "   ✗ pydantic not installed (run: pip install -r requirements.txt)"
fi

if python3 -c "import psycopg2" 2>/dev/null; then
    echo "   ✓ psycopg2 installed"
else
    echo "   ✗ psycopg2 not installed (run: pip install -r requirements.txt)"
fi
echo ""

# Check .env file
echo "3. Checking configuration..."
if [ -f ".env" ]; then
    echo "   ✓ .env file exists"
else
    echo "   ✗ .env file not found (copy from .env.example)"
fi
echo ""

# Check project structure
echo "4. Checking project structure..."
if [ -d "validator" ]; then
    echo "   ✓ validator/ directory exists"
else
    echo "   ✗ validator/ directory missing"
fi

if [ -d "miner" ]; then
    echo "   ✓ miner/ directory exists"
else
    echo "   ✗ miner/ directory missing"
fi

if [ -d "tests" ]; then
    echo "   ✓ tests/ directory exists"
else
    echo "   ✗ tests/ directory missing"
fi
echo ""

# Check key files
echo "5. Checking key files..."
files=(
    "validator/validator.py"
    "validator/models.py"
    "validator/backtester.py"
    "miner/miner.py"
    "miner/strategy.py"
    "requirements.txt"
    "README.md"
)

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo "   ✓ $file"
    else
        echo "   ✗ $file missing"
    fi
done
echo ""

# Test imports
echo "6. Testing Python imports..."
if python3 -c "from validator.models import ValidatorRequest, MinerResponse" 2>/dev/null; then
    echo "   ✓ validator.models imports successfully"
else
    echo "   ✗ validator.models import failed"
fi

if python3 -c "from validator.backtester import Backtester" 2>/dev/null; then
    echo "   ✓ validator.backtester imports successfully"
else
    echo "   ✗ validator.backtester import failed"
fi

if python3 -c "from miner.strategy import SimpleStrategyGenerator" 2>/dev/null; then
    echo "   ✓ miner.strategy imports successfully"
else
    echo "   ✗ miner.strategy import failed"
fi
echo ""

echo "======================================"
echo "Verification Complete!"
echo "======================================"
echo ""
echo "Next steps:"
echo "  1. Configure .env file with your credentials"
echo "  2. For validators: python -m validator.main --help"
echo "  3. For miners: python -m miner.miner"
echo "  4. Run tests: pytest tests/"
echo ""
