#!/usr/bin/env bash
# Run the Docker infrastructure (PostgreSQL, Redis, etc.)
# Ensure you are in the project root directory
cd "$(dirname "$0")"

echo "Starting Docker infrastructure..."
cd deploy && docker-compose up -d

echo "Infrastructure is running!"
