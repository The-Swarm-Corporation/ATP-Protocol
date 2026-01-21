"""
Client example for Anthropic API + ATP Protocol

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


def chat_completions():
    """Example 1: Chat completions (OpenAI-compatible format)"""
    print("\n=== Example 1: Chat Completions ===\n")
    
    response = httpx.post(
        f"{API_BASE_URL}/v1/chat/completions",
        headers=headers,
        json={
            "model": "claude-3-5-sonnet-20241022",
            "messages": [
                {"role": "user", "content": "What are the key benefits of using AI agents?"}
            ],
            "max_tokens": 1024,
        },
        timeout=60.0,
    )
    response.raise_for_status()
    data = response.json()
    
    print("Response:")
    print(json.dumps(data, indent=2))
    return data


def messages_api():
    """Example 2: Anthropic Messages API"""
    print("\n=== Example 2: Anthropic Messages API ===\n")
    
    response = httpx.post(
        f"{API_BASE_URL}/v1/messages",
        headers=headers,
        json={
            "model": "claude-3-5-sonnet-20241022",
            "messages": [
                {"role": "user", "content": "Explain the concept of agentic AI in simple terms."}
            ],
            "max_tokens": 1024,
            "system": "You are a helpful AI assistant that explains complex concepts clearly.",
        },
        timeout=60.0,
    )
    response.raise_for_status()
    data = response.json()
    
    print("Response:")
    print(json.dumps(data, indent=2))
    return data


def conversation_example():
    """Example 3: Multi-turn conversation"""
    print("\n=== Example 3: Multi-turn Conversation ===\n")
    
    # First message
    response1 = httpx.post(
        f"{API_BASE_URL}/v1/messages",
        headers=headers,
        json={
            "model": "claude-3-5-sonnet-20241022",
            "messages": [
                {"role": "user", "content": "What is machine learning?"}
            ],
            "max_tokens": 1024,
        },
        timeout=60.0,
    )
    response1.raise_for_status()
    data1 = response1.json()
    
    print("First message response:")
    print(json.dumps(data1, indent=2))
    
    # Follow-up message
    assistant_response = ""
    if "content" in data1 and len(data1["content"]) > 0:
        assistant_response = data1["content"][0].get("text", "")
    
    response2 = httpx.post(
        f"{API_BASE_URL}/v1/messages",
        headers=headers,
        json={
            "model": "claude-3-5-sonnet-20241022",
            "messages": [
                {"role": "user", "content": "What is machine learning?"},
                {"role": "assistant", "content": assistant_response},
                {"role": "user", "content": "Can you give me a practical example?"}
            ],
            "max_tokens": 1024,
        },
        timeout=60.0,
    )
    response2.raise_for_status()
    data2 = response2.json()
    
    print("\nFollow-up response:")
    print(json.dumps(data2, indent=2))
    return data2


def health_check():
    """Example 4: Health check (no authentication required)"""
    print("\n=== Example 4: Health Check ===\n")
    
    response = httpx.get(f"{API_BASE_URL}/v1/health", timeout=10.0)
    response.raise_for_status()
    data = response.json()
    
    print("Response:")
    print(json.dumps(data, indent=2))
    return data


if __name__ == "__main__":
    print("Anthropic API + ATP Protocol Client Example")
    print("=" * 50)
    
    if not WALLET_PRIVATE_KEY:
        print("WARNING: ATP_PRIVATE_KEY not set in environment variables")
        print("Payment-enabled endpoints will fail without this key")
    
    try:
        # Run examples
        health_check()
        chat_completions()
        messages_api()
        conversation_example()
        
        print("\n" + "=" * 50)
        print("All examples completed successfully!")
        
    except httpx.HTTPStatusError as e:
        print(f"\nHTTP Error: {e.response.status_code}")
        print(f"Response: {e.response.text}")
    except Exception as e:
        print(f"\nError: {e}")

