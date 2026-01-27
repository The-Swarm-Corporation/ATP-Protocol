import os
from atp.client import ATPClient
import asyncio
from dotenv import load_dotenv

load_dotenv()

wallet_key = os.getenv("ATP_PRIVATE_KEY")
endpoint_url = "http://localhost:8000/v1/agent/execute"


client = ATPClient(wallet_private_key=wallet_key)

response = asyncio.run(client.post(
    url=endpoint_url,
    json={
        "task": "What are the key benefits of using a multi-agent system?",
        "system_prompt": "You are a helpful AI assistant."
    }
))
print(response)
