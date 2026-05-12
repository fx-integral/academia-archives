#!/bin/bash
set -e

alembic upgrade head

exec uvicorn subnet_validator.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"