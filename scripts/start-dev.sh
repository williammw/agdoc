#!/bin/bash

# AGDOC Development Server Start Script
# Starts FastAPI server on port 8000

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "=========================================="
echo "  AGDOC - FastAPI Media Processing API"
echo "=========================================="
echo "  Local:  http://localhost:8000"
echo "  Remote: https://dev.ohmeowkase.com"
echo "  Docs:   http://localhost:8000/docs"
echo "=========================================="

# Check if virtual environment exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
elif [ -d ".venv" ]; then
    echo "Activating .venv..."
    source .venv/bin/activate
else
    echo "Warning: No virtual environment found. Using system Python."
fi

# Check if uvicorn is installed
if ! command -v uvicorn &> /dev/null; then
    echo "Error: uvicorn not found. Please install requirements first:"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Load environment variables
if [ -f ".env" ]; then
    echo "Loading environment variables from .env..."
    set -a
    source .env
    set +a
fi

# Start the server
echo ""
echo "Starting FastAPI server..."
echo ""

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
