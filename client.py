"""
Client example for ATP Protocol + Swarms API

This example shows how to call the API endpoints with wallet authentication.
Replace the placeholder values with your actual credentials.
"""

import json
import httpx
import os

from dotenv import load_dotenv

load_dotenv()

# API configuration
API_BASE_URL = "http://localhost:8000"
WALLET_PRIVATE_KEY = os.getenv("ATP_PRIVATE_KEY")

# Headers for authenticated requests
headers = {
    "Content-Type": "application/json",
    "x-wallet-private-key": WALLET_PRIVATE_KEY,
}

# Example 1: Execute agent task
execute_response = httpx.post(
    f"{API_BASE_URL}/v1/agent/execute",
    headers=headers,
    json={
        "task": "What are the key benefits of using a multi-agent system?",
        "system_prompt": "You are a helpful AI assistant.",
    },
    timeout=60.0,
)
execute_data = execute_response.json()

print(json.dumps(execute_data, indent=2))

# Example 4: Health check (no authentication required)
health_response = httpx.get(f"{API_BASE_URL}/v1/health", timeout=10.0)
health_data = health_response.json()
print(json.dumps(health_data, indent=2))