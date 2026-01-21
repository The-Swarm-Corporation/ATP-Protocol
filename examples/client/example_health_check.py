import os
from atp.client import ATPClient
import asyncio

api_key = os.getenv("ATP_API_KEY")

client = ATPClient()

health = asyncio.run(client.health_check())
print(health)
