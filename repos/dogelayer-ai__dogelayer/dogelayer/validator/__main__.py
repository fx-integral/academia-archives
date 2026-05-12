#!/usr/bin/env python3

"""
DogeLayer Validator Main Entry Point

This module serves as the main entry point for the DogeLayer validator
when run as a Python module using: python -m dogelayer.validator.validator
"""

import sys
import os

# Add the parent directory to the Python path to ensure proper imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

if __name__ == "__main__":
    from dogelayer.validator.validator import main
    main()
