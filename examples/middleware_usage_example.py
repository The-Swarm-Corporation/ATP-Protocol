"""
Example: Using ATP Settlement Middleware

This example shows how to add ATP settlement to any FastAPI endpoint.

The middleware accepts wallet private keys directly via headers, making it
simple to use. Users can add their own API key handling layer if needed.
"""

from fastapi import Depends, FastAPI, Header, HTTPException
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
        "/v1/agent/execute",
    ],
    input_cost_per_million_usd=10.0,  # $10 per million input tokens
    output_cost_per_million_usd=30.0,  # $30 per million output tokens
    wallet_private_key_header="x-wallet-private-key",  # Header name for wallet private key
    payment_token=PaymentToken.SOL,  # Payment token (SOL or USDC)
    # Note: treasury_pubkey is immutable and always uses config.SWARMS_TREASURY_PUBKEY
    skip_preflight=False,
    commitment="confirmed",
    usage_response_key="usage",  # Key in response where usage data is located
    include_usage_in_response=True,  # Add usage/cost info to response
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


# Example: Adding your own API key handling layer
# You can create a dependency or middleware to map API keys to wallet private keys

# Simple in-memory mapping (replace with database in production)
API_KEY_TO_WALLET = {
    "user_api_key_123": "[1,2,3,...]",  # Solana private key
}


def get_wallet_from_api_key(api_key: str = Header(..., alias="x-api-key")) -> str:
    """Custom dependency to map API keys to wallet private keys."""
    if api_key not in API_KEY_TO_WALLET:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return API_KEY_TO_WALLET[api_key]


@app.post("/v1/chat-with-api-key")
async def chat_with_api_key(
    request: dict, wallet_private_key: str = Depends(get_wallet_from_api_key)
):
    """Example endpoint with custom API key handling.

    The wallet private key is extracted from the API key and can be
    passed to the middleware via a custom header.
    """
    # In a real implementation, you'd set the header before calling the endpoint
    # or use a custom middleware to inject it
    pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
