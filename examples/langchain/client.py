"""
Client example for LangChain + ATP Protocol API

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


def run_agent_task():
    """Example 1: Execute LangChain agent task"""
    print("\n=== Example 1: Execute LangChain Agent Task ===\n")
    
    response = httpx.post(
        f"{API_BASE_URL}/v1/agent/run",
        headers=headers,
        json={
            "task": "What is 25 * 37? Use the calculator tool.",
            "input": "Calculate 25 * 37",
        },
        timeout=60.0,
    )
    response.raise_for_status()
    data = response.json()
    
    print("Response:")
    print(json.dumps(data, indent=2))
    return data


def chat_with_agent():
    """Example 2: Chat with LangChain agent"""
    print("\n=== Example 2: Chat with LangChain Agent ===\n")
    
    response = httpx.post(
        f"{API_BASE_URL}/v1/agent/chat",
        headers=headers,
        json={
            "message": "What is the square root of 144?",
        },
        timeout=60.0,
    )
    response.raise_for_status()
    data = response.json()
    
    print("Response:")
    print(json.dumps(data, indent=2))
    return data


def health_check():
    """Example 3: Health check (no authentication required)"""
    print("\n=== Example 3: Health Check ===\n")
    
    response = httpx.get(f"{API_BASE_URL}/v1/health", timeout=10.0)
    response.raise_for_status()
    data = response.json()
    
    print("Response:")
    print(json.dumps(data, indent=2))
    return data


if __name__ == "__main__":
    print("LangChain + ATP Protocol Client Example")
    print("=" * 50)
    
    if not WALLET_PRIVATE_KEY:
        print("WARNING: ATP_PRIVATE_KEY not set in environment variables")
        print("Payment-enabled endpoints will fail without this key")
    
    try:
        # Run examples
        health_check()
        run_agent_task()
        chat_with_agent()
        
        print("\n" + "=" * 50)
        print("All examples completed successfully!")
        
    except httpx.HTTPStatusError as e:
        print(f"\nHTTP Error: {e.response.status_code}")
        print(f"Response: {e.response.text}")
    except Exception as e:
        print(f"\nError: {e}")

