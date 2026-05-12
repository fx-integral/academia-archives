#!/bin/bash
set -a
source validator.env
set +a

export PYTHONPATH=$(pwd):$PYTHONPATH

./venv/bin/python natix/validator/scripts/run_cache_updater.py