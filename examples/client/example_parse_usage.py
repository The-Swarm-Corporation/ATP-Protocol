from atp.client import ATPClient
import asyncio

client = ATPClient()

usage_data = {
    "prompt_tokens": 100,
    "completion_tokens": 50,
    "total_tokens": 150
}

parsed = asyncio.run(client.parse_usage(usage_data))
print(parsed)
