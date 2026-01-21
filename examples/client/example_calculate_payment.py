from atp.client import ATPClient
from atp.schemas import PaymentToken
import asyncio

client = ATPClient()

usage = {"input_tokens": 1000, "output_tokens": 500}

payment = asyncio.run(client.calculate_payment(
    usage=usage,
    input_cost_per_million_usd=10.0,
    output_cost_per_million_usd=30.0,
    payment_token=PaymentToken.SOL
))
print(payment)
