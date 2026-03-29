#!/usr/bin/env bash
# Run the test suite for AIDEN
# Ensure you are in the project root directory
cd "$(dirname "$0")"

# Activate virtual environment if needed (uncomment and adjust path)
source .venv/bin/activate

echo "Running AIDEN tests..."
pytest
