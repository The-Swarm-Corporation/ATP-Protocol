"""
Client example for ATP Protocol + Swarms API

This example shows how to call the API endpoints with wallet authentication.
Replace the placeholder values with your actual credentials.
"""

import json
import httpx

from dotenv import load_dotenv
import traceback

load_dotenv()

# API configuration
API_BASE_URL = "http://localhost:8000"
WALLET_PRIVATE_KEY = "434311"

# Headers for authenticated requests
headers = {
    "Content-Type": "application/json",
    "x-wallet-private-key": WALLET_PRIVATE_KEY,
}


# Example 1: Execute agent task
try:
    execute_response = httpx.post(
        f"{API_BASE_URL}/v1/agent/execute",
        headers=headers,
        json={
            "task": "What are the key benefits of using a multi-agent system?",
            "system_prompt": "You are a helpful AI assistant.",
        },
        timeout=60.0,
    )
    execute_response.raise_for_status()  # Raise exception for bad status codes
    execute_data = execute_response.json()
    print(json.dumps(execute_data, indent=2))
except httpx.HTTPError as e:
    print(f"HTTP error occurred: {e}")
    traceback.print_exc()
    if hasattr(e, 'response') and e.response is not None:
        try:
            error_data = e.response.json()
            print(f"Error details: {json.dumps(error_data, indent=2)}")
        except (json.JSONDecodeError, ValueError):
            print(f"Error response: {e.response.text}")
except Exception as e:
    print(f"Unexpected error: {e}")
    traceback.print_exc()
