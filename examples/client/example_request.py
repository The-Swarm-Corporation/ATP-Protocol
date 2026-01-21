import os
from atp.client import ATPClient
import asyncio

wallet_key = os.getenv("ATP_WALLET_PRIVATE_KEY")
endpoint_url = os.getenv("ATP_ENDPOINT_URL", "http://localhost:8000/v1/chat")

client = ATPClient(wallet_private_key=wallet_key)

response = asyncio.run(client.post(
    url=endpoint_url,
    json={"message": "Hello!"}
))
print(response)
