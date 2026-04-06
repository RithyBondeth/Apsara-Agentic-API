#!/bin/bash

# Apsara Agentic API Development Runner
# This script runs the FastAPI application in development mode with hot-reloading.

echo "🚀 Starting Apsara Agentic API in development mode..."

# Check if requirements are installed (optional but recommended)
# python3 -m pip install -r requirements.txt

# Run the application
python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
