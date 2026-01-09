"""
Anthropic API + ATP Protocol Integration Example

This example demonstrates how to integrate ATP Protocol with Anthropic's API
to enable automatic payment processing for Anthropic-based services.

Installation:
    pip install anthropic swarms atp-protocol fastapi uvicorn

Environment Variables:
    ANTHROPIC_API_KEY="your-anthropic-api-key"
    # Optional: Configure ATP settings
    ATP_SETTLEMENT_URL="https://facilitator.swarms.world"
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger
import anthropic
from typing import Dict, Any, List, Optional
from swarms import count_tokens

from atp.middleware import ATPSettlementMiddleware
from atp.schemas import PaymentToken

# Create FastAPI app
app = FastAPI(
    title="Anthropic API + ATP Protocol Integration",
    description="Example API showing ATP payment processing with Anthropic's Claude API",
)

# Model name for token counting (used as fallback)
AGENT_MODEL = "claude-3-5-sonnet-20241022"

# Initialize Anthropic client
client = anthropic.Anthropic()

# Add ATP Settlement Middleware
app.add_middleware(
    ATPSettlementMiddleware,
    allowed_endpoints=[
        "/v1/chat/completions",
        "/v1/messages",
    ],
    input_cost_per_million_usd=10.0,  # $10 per million input tokens
    output_cost_per_million_usd=30.0,  # $30 per million output tokens
    recipient_pubkey="YourSolanaWalletHere",  # Your wallet receives 95% of payments
    payment_token=PaymentToken.SOL,  # Use SOL for payments
    wallet_private_key_header="x-wallet-private-key",  # Header for client wallet key
    require_wallet=True,  # Require wallet key for payment
)


@app.post("/v1/chat/completions")
async def chat_completions(request: dict):
    """
    Chat completions endpoint compatible with Anthropic's API format.

    Request:
        {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [
                {"role": "user", "content": "Hello!"}
            ],
            "max_tokens": 1024
        }

    Response includes completion and payment details.
    """
    try:
        model = request.get("model", "claude-3-5-sonnet-20241022")
        messages = request.get("messages", [])
        max_tokens = request.get("max_tokens", 1024)
        system = request.get("system")

        if not messages:
            raise HTTPException(
                status_code=400, detail="Messages are required"
            )

        # Convert messages to Anthropic format
        anthropic_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                anthropic_messages.append({
                    "role": "user",
                    "content": content
                })
            elif role == "assistant":
                anthropic_messages.append({
                    "role": "assistant",
                    "content": content
                })

        # Call Anthropic API
        logger.info(f"Anthropic API request: {len(messages)} messages")
        
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=anthropic_messages,
            system=system,
        )

        # Extract response content
        response_text = ""
        if response.content:
            for block in response.content:
                if hasattr(block, 'text'):
                    response_text += block.text
                elif isinstance(block, str):
                    response_text += block

        # Extract usage from Anthropic response
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }

        # Return response with usage data
        # The ATP middleware will automatically:
        # 1. Extract usage data
        # 2. Calculate payment
        # 3. Process Solana transaction
        # 4. Add settlement info to response
        response_data = {
            "id": response.id,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response_text,
                    },
                    "finish_reason": response.stop_reason,
                }
            ],
            "usage": usage,
        }

        return JSONResponse(content=response_data)

    except Exception as e:
        logger.error(f"Anthropic API error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Anthropic API call failed: {str(e)}"
        )


@app.post("/v1/messages")
async def messages(request: dict):
    """
    Anthropic Messages API endpoint.

    Request:
        {
            "model": "claude-3-5-sonnet-20241022",
            "messages": [
                {"role": "user", "content": "Hello!"}
            ],
            "max_tokens": 1024,
            "system": "You are a helpful assistant"  # Optional
        }

    Response includes message and payment details.
    """
    try:
        model = request.get("model", "claude-3-5-sonnet-20241022")
        messages = request.get("messages", [])
        max_tokens = request.get("max_tokens", 1024)
        system = request.get("system")

        if not messages:
            raise HTTPException(
                status_code=400, detail="Messages are required"
            )

        # Convert messages to Anthropic format
        anthropic_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                anthropic_messages.append({
                    "role": "user",
                    "content": content
                })
            elif role == "assistant":
                anthropic_messages.append({
                    "role": "assistant",
                    "content": content
                })

        # Call Anthropic API
        logger.info(f"Anthropic Messages API request: {len(messages)} messages")
        
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=anthropic_messages,
            system=system,
        )

        # Extract response content
        response_text = ""
        if response.content:
            for block in response.content:
                if hasattr(block, 'text'):
                    response_text += block.text
                elif isinstance(block, str):
                    response_text += block

        # Extract usage from Anthropic response
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }

        # Return response with usage data
        response_data = {
            "id": response.id,
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": response_text,
                }
            ],
            "model": model,
            "stop_reason": response.stop_reason,
            "stop_sequence": response.stop_sequence,
            "usage": usage,
        }

        return JSONResponse(content=response_data)

    except Exception as e:
        logger.error(f"Anthropic Messages API error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Anthropic API call failed: {str(e)}"
        )


@app.get("/v1/health")
async def health_check():
    """
    Health check endpoint (not protected by ATP middleware).
    """
    return {
        "status": "healthy",
        "api_ready": True,
        "atp_middleware": "active",
        "provider": "anthropic",
    }


@app.get("/")
async def root():
    """
    Root endpoint with API information.
    """
    return {
        "name": "Anthropic API + ATP Protocol Integration",
        "description": "API for Anthropic's Claude with automatic payment processing",
        "endpoints": {
            "/v1/chat/completions": "Chat completions (requires x-wallet-private-key header)",
            "/v1/messages": "Messages API (requires x-wallet-private-key header)",
            "/v1/health": "Health check (no payment required)",
        },
        "payment": {
            "token": "SOL",
            "input_rate": "$10 per million tokens",
            "output_rate": "$30 per million tokens",
            "fee": "5% to Swarms Treasury",
        },
    }


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Anthropic API + ATP Protocol Integration API...")
    logger.info("Make sure to set ANTHROPIC_API_KEY environment variable")
    logger.info(
        "Update recipient_pubkey in middleware configuration with your Solana wallet"
    )

    uvicorn.run(app, host="0.0.0.0", port=8000)

