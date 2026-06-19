#!/bin/bash
# Machine Downtime Log - Startup Script
# Demonstrates port checking and proper startup sequence....

echo "🚀 Starting Machine Downtime Log..."

# Check if .env exists, if not copy from example
if [ ! -f hermes/.env ]; then
    if [ -f hermes/.env.example ]; then
        echo "📋 Copying hermes/.env.example to hermes/.env"
        cp hermes/.env.example hermes/.env
        echo "⚠️  Please edit hermes/.env to add your actual values:"
        echo "   - GITHUB_TOKEN"
        echo "   - LLM_API_KEY (if different from example)"
        echo "   - Any other custom configuration"
    else
        echo "❌ hermes/.env.example not found!"
        exit 1
    fi
fi

# Source environment variables
if [ -f hermes/.env ]; then
    echo "📋 Loading environment from hermes/.env"
    # Export variables but don't source to avoid executing arbitrary code
    set -a
    . hermes/.env
    set +a
fi

# Check if required variables are set
if [ -z "$GITHUB_TOKEN" ] || [ "$GITHUB_TOKEN" = "your_github_token_here" ]; then
    echo "⚠️  Warning: GITHUB_TOKEN not set in hermes/.env"
    echo "   GitHub push functionality will not work until configured"
fi

if [ -z "$LLM_API_KEY" ] || [ "$LLM_API_KEY" = "your_llm_api_key_here" ]; then
    echo "⚠️  Warning: LLM_API_KEY not set in hermes/.env"
    echo "   LLM classification will use fallback values"
fi

# Start the application using docker compose
echo "🐳 Starting application with Docker Compose..."
echo "📋 Configuration:"
echo "   APP_PORT: ${APP_PORT:-8742}"
echo "   LLM_BASE_URL: ${LLM_BASE_URL:-http://ray-serve-llama.apps.rtp-ai1-ucs.svpod.dc-01.com/v1}"
echo "   DB_PATH: ${DB_PATH:-/data/downtime.db}"
echo "   SIMULATOR_ENABLED: ${SIMULATOR_ENABLED:-true}"

docker compose up --build

echo "✅ Application started successfully!"
echo "🌐 Access the dashboard at: http://localhost:${APP_PORT:-8742}"
