#!/usr/bin/env bash
# Run the FastAPI backend with WebSocket support
# Ensure you are in the project root directory
cd "$(dirname "$0")"
# Activate virtual environment if needed (uncomment and adjust path)
source .venv/bin/activate
uvicorn src.api.main:app --reload
