#!/usr/bin/env bash
# Setup the AIDEN application environment
# Ensure you are in the project root directory
cd "$(dirname "$0")"

echo "Setting up AIDEN project..."

# Create a virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Install dependencies in editable mode
echo "Installing dependencies..."
pip install -e .

echo "Setup complete! You can now run the infrastructure and application scripts."
