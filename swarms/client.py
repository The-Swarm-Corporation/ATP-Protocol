"""
Swarms + ATP Protocol Client Example

Simple example showing:
1. Automatic settlement - Let the server middleware handle payment
2. Manual settlement - Use client.settle() to pay directly
"""

import asyncio
import os
import json
from dotenv import load_dotenv
from atp.client import ATPClient

load_dotenv()

# Configuration
API_BASE_URL = "http://localhost:8000"
WALLET_PRIVATE_KEY = os.getenv("ATP_PRIVATE_KEY")

# Initialize client
client = ATPClient(wallet_private_key=WALLET_PRIVATE_KEY)


async def settle_payment():
    """Example 1: Automatic settlement via server middleware"""
    print("\n=== Example 1: Automatic Settlement (Middleware) ===")
    
    response = await client.post(
        url=f"{API_BASE_URL}/v1/agent/execute",
        json={
            "task": "What are the key benefits of using a multi-agent system?",
            "system_prompt": "You are a helpful AI assistant."
        }
    )
    
    return response


if __name__ == "__main__":
    asyncio.run(print(json.dumps(settle_payment(), indent=4)))

