"""
Example demonstrating how to use the ATP Settlement Service.

This example shows:
1. How to run the settlement service as a standalone FastAPI server
2. How to use the middleware with the settlement service
3. How to call the settlement service directly via HTTP
"""

import asyncio
import json
from typing import Any, Dict

import httpx
from fastapi import FastAPI

from atp.middleware import ATPSettlementMiddleware
from atp.settlement_client import SettlementServiceClient
from atp.schemas import PaymentToken

# Example 1: Run the settlement service standalone
# You can run this with: uvicorn atp.settlement_service:settlement_app --port 8001


# Example 2: Use middleware with settlement service
def create_app_with_settlement_service():
    """Create a FastAPI app that uses the middleware with settlement service."""
    app = FastAPI(title="Example App with Settlement Service")

    # Add middleware that delegates to settlement service
    # The middleware uses ATP_SETTLEMENT_URL environment variable by default
    # You can override it by passing settlement_service_url parameter
    app.add_middleware(
        ATPSettlementMiddleware,
        allowed_endpoints=["/v1/chat", "/v1/completions"],
        input_cost_per_million_usd=10.0,
        output_cost_per_million_usd=30.0,
        wallet_private_key_header="x-wallet-private-key",
        payment_token=PaymentToken.SOL,
        recipient_pubkey="YourRecipientPubkeyHere",  # Replace with actual pubkey
        # settlement_service_url is optional - uses ATP_SETTLEMENT_URL env var by default
    )

    @app.post("/v1/chat")
    async def chat_endpoint(request: Dict[str, Any]):
        """Example chat endpoint that returns usage data."""
        # Simulate an LLM response with usage
        return {
            "output": "This is a simulated response",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }

    return app


# Example 3: Call settlement service directly
async def example_direct_service_call():
    """Example of calling the settlement service directly via HTTP."""
    client = SettlementServiceClient(base_url="http://localhost:8001")

    # Example usage data (OpenAI format)
    usage_data = {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
    }

    # 1. Parse usage tokens
    print("1. Parsing usage tokens...")
    parsed = await client.parse_usage(usage_data)
    print(f"Parsed tokens: {parsed}")

    # 2. Calculate payment
    print("\n2. Calculating payment...")
    payment_calc = await client.calculate_payment(
        usage=usage_data,
        input_cost_per_million_usd=10.0,
        output_cost_per_million_usd=30.0,
        payment_token="SOL",
    )
    print(
        f"Payment calculation: {json.dumps(payment_calc, indent=2)}"
    )

    # 3. Execute settlement (requires private key - DO NOT use real keys in examples)
    print("\n3. Executing settlement...")
    # NOTE: This is just an example. In production, never expose private keys.
    # private_key = "[1,2,3,...]"  # Your wallet private key
    # recipient_pubkey = "YourRecipientPubkeyHere"
    #
    # settlement_result = await client.settle(
    #     private_key=private_key,
    #     usage=usage_data,
    #     input_cost_per_million_usd=10.0,
    #     output_cost_per_million_usd=30.0,
    #     recipient_pubkey=recipient_pubkey,
    #     payment_token="SOL",
    # )
    # print(f"Settlement result: {json.dumps(settlement_result, indent=2)}")

    # 4. Health check
    print("\n4. Checking service health...")
    health = await client.health_check()
    print(f"Health status: {health}")


# Example 4: Call settlement service via raw HTTP
async def example_raw_http_call():
    """Example of calling the settlement service via raw HTTP requests."""
    base_url = "http://localhost:8001"

    # Example usage data
    usage_data = {
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
    }

    async with httpx.AsyncClient() as client:
        # Parse usage
        response = await client.post(
            f"{base_url}/v1/settlement/parse-usage",
            json={"usage_data": usage_data},
        )
        print(f"Parse usage response: {response.json()}")

        # Calculate payment
        response = await client.post(
            f"{base_url}/v1/settlement/calculate-payment",
            json={
                "usage": usage_data,
                "input_cost_per_million_usd": 10.0,
                "output_cost_per_million_usd": 30.0,
                "payment_token": "SOL",
            },
        )
        print(f"Calculate payment response: {response.json()}")

        # Health check
        response = await client.get(f"{base_url}/health")
        print(f"Health check response: {response.json()}")


if __name__ == "__main__":
    print("ATP Settlement Service Examples")
    print("=" * 50)
    print("\nTo run these examples:")
    print("1. Start the settlement service:")
    print(
        "   uvicorn atp.settlement_service:settlement_app --port 8001"
    )
    print("\n2. Run this example:")
    print("   python examples/settlement_service_example.py")
    print("\n" + "=" * 50)

    # Run async examples
    asyncio.run(example_direct_service_call())
    print("\n" + "=" * 50)
    asyncio.run(example_raw_http_call())
