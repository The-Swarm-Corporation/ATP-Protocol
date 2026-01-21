import os
from atp.client import ATPClient
from atp.schemas import PaymentToken
import asyncio

wallet_key = os.getenv("ATP_WALLET_PRIVATE_KEY")
recipient = os.getenv("ATP_RECIPIENT_PUBKEY", "RecipientPublicKeyHere")

client = ATPClient(wallet_private_key=wallet_key)

usage = {"input_tokens": 1000, "output_tokens": 500}

result = asyncio.run(client.settle(
    usage=usage,
    input_cost_per_million_usd=10.0,
    output_cost_per_million_usd=30.0,
    recipient_pubkey=recipient,
    payment_token=PaymentToken.SOL
))
print(result)
