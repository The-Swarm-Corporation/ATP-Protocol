"""
Example: Using ATP Settlement Middleware

This example shows how to add ATP settlement to any FastAPI endpoint.

The middleware accepts wallet private keys directly via headers, making it
simple to use.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from atp.middleware import ATPSettlementMiddleware
from atp.schemas import PaymentToken

# Create FastAPI app
app = FastAPI(title="ATP Settlement Example")

# Add the middleware
app.add_middleware(
    ATPSettlementMiddleware,
    allowed_endpoints=[
        "/v1/chat",
        "/v1/completions",
    ],
    input_cost_per_million_usd=10.0,  # $10 per million input tokens
    output_cost_per_million_usd=30.0,  # $30 per million output tokens
    wallet_private_key_header="x-wallet-private-key",  # Header name for wallet private key
    payment_token=PaymentToken.SOL,  # Payment token (SOL or USDC)
    recipient_pubkey="YourRecipientPublicKeyHere",  # Required: recipient wallet public key
    # Note: treasury_pubkey is automatically set from SWARMS_TREASURY_PUBKEY
    # environment variable on the settlement service and cannot be overridden
    skip_preflight=False,
    commitment="confirmed",
    require_wallet=True,  # Require wallet private key for these endpoints
)


# Example endpoint that returns usage data
@app.post("/v1/chat")
async def chat_endpoint(request: dict):
    """Example chat endpoint that returns usage data."""
    # Your endpoint logic here
    response_data = {
        "output": "Hello! This is a response from the chat endpoint.",
        "usage": {
            "input_tokens": 150,  # Tokens in the request
            "output_tokens": 50,  # Tokens in the response
            "total_tokens": 200,
        },
    }
    return JSONResponse(content=response_data)


# Example endpoint with different usage format
@app.post("/v1/completions")
async def completions_endpoint(request: dict):
    """Example completions endpoint with OpenAI-style usage."""
    response_data = {
        "choices": [{"text": "Generated completion text"}],
        "usage": {
            "prompt_tokens": 200,  # OpenAI-style naming
            "completion_tokens": 100,
            "total_tokens": 300,
        },
    }
    return JSONResponse(content=response_data)


# Example endpoint without usage (will skip settlement)
@app.get("/v1/health")
async def health_check():
    """Health check endpoint - not in allowed_endpoints, so no settlement."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
