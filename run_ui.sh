#!/usr/bin/env bash
# Run the Streamlit UI for AIDEN
# Ensure you are in the project root directory
cd "$(dirname "$0")"
# Activate virtual environment if needed (uncomment and adjust path)
source .venv/bin/activate
streamlit run ui/app.py
