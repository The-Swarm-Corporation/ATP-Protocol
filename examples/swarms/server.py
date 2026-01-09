"""
Swarms Framework + ATP Protocol Integration Example

This example demonstrates how to integrate ATP Protocol with Swarms agents
to enable automatic payment processing for agent services.

The example shows:
1. Setting up a Swarms agent
2. Creating a FastAPI API with ATP middleware
3. Automatic payment processing after agent execution
4. Usage tracking and billing

Installation:
    pip install swarms atp-protocol fastapi uvicorn

Environment Variables:
    OPENAI_API_KEY="your-openai-api-key"
    # Optional: Configure ATP settings
    ATP_SETTLEMENT_URL="https://facilitator.swarms.world"
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger
from swarms import Agent, count_tokens

from atp.middleware import ATPSettlementMiddleware
from atp.schemas import PaymentToken

# Create FastAPI app
app = FastAPI(
    title="ATP Protocol + Swarms Integration",
    description="Example API showing ATP payment processing with Swarms agents",
)

# Initialize Swarms Agent
# This agent will be used to process tasks
AGENT_MODEL = "gpt-4o-mini"  # Model name for agent and token counting
agent = Agent(
    model_name=AGENT_MODEL,  # Specify the LLM
    max_loops=1,  # Set the number of interactions
    interactive=False,  # Disable interactive mode for API use
)

# Add ATP Settlement Middleware
# This automatically processes payments after agent execution
app.add_middleware(
    ATPSettlementMiddleware,
    allowed_endpoints=[
        "/v1/agent/execute",
        "/v1/agent/chat",
    ],
    input_cost_per_million_usd=10.0,  # $10 per million input tokens
    output_cost_per_million_usd=30.0,  # $30 per million output tokens
    recipient_pubkey="YourSolanaWalletHere",  # Your wallet receives 95% of payments
    payment_token=PaymentToken.SOL,  # Use SOL for payments
    wallet_private_key_header="x-wallet-private-key",  # Header for client wallet key
    require_wallet=True,  # Require wallet key for payment
)


@app.post("/v1/agent/execute")
async def execute_agent(request: dict):
    """
    Execute a Swarms agent task with automatic payment processing.

    Request:
        {
            "task": "Your task description here",
            "system_prompt": "Optional system prompt"
        }

    Response includes:
        - Agent output
        - Usage data (for billing)
        - ATP settlement information (payment details)
    """
    try:
        # Extract task from request
        task = request.get("task", "")
        if not task:
            raise HTTPException(
                status_code=400, detail="Task is required"
            )

        # Optional system prompt
        system_prompt = request.get("system_prompt")

        # Count input tokens using Swarms tokenizer
        input_tokens = count_tokens(task, model=AGENT_MODEL)
        if system_prompt:
            input_tokens += count_tokens(system_prompt, model=AGENT_MODEL)

        # Execute the agent
        logger.info(f"Executing agent task: {task[:100]}...")
        result = agent.run(task)

        # Count output tokens using Swarms tokenizer
        output_tokens = count_tokens(str(result), model=AGENT_MODEL)

        # Return response with usage data
        # The ATP middleware will automatically:
        # 1. Extract usage data
        # 2. Calculate payment
        # 3. Process Solana transaction
        # 4. Add settlement info to response
        response_data = {
            "output": result,
            "task": task,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        }

        return JSONResponse(content=response_data)

    except Exception as e:
        logger.error(f"Agent execution error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Agent execution failed: {str(e)}"
        )


@app.post("/v1/agent/chat")
async def chat_with_agent(request: dict):
    """
    Chat with a Swarms agent (conversational interface).

    Request:
        {
            "message": "Your message here",
            "conversation_history": []  # Optional conversation history
        }

    Response includes agent response and payment details.
    """
    try:
        message = request.get("message", "")
        if not message:
            raise HTTPException(
                status_code=400, detail="Message is required"
            )

        # Get conversation history if provided
        history = request.get("conversation_history", [])

        # Build context from history
        context = ""
        if history:
            context = "\n".join(
                [
                    f"User: {h.get('user', '')}\nAssistant: {h.get('assistant', '')}"
                    for h in history
                ]
            )

        # Combine context and current message
        full_task = f"{context}\n\nUser: {message}\nAssistant:" if context else message

        # Count input tokens using Swarms tokenizer
        input_tokens = count_tokens(full_task, model=AGENT_MODEL)

        # Execute agent
        logger.info(f"Chat request: {message[:100]}...")
        response = agent.run(full_task)

        # Count output tokens using Swarms tokenizer
        output_tokens = count_tokens(str(response), model=AGENT_MODEL)

        # Return response with usage
        response_data = {
            "message": message,
            "response": response,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        }

        return JSONResponse(content=response_data)

    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Chat failed: {str(e)}"
        )


@app.get("/v1/health")
async def health_check():
    """
    Health check endpoint (not protected by ATP middleware).
    """
    return {
        "status": "healthy",
        "agent_ready": True,
        "atp_middleware": "active",
        "framework": "swarms",
    }


@app.get("/")
async def root():
    """
    Root endpoint with API information.
    """
    return {
        "name": "ATP Protocol + Swarms Integration",
        "description": "API for Swarms agents with automatic payment processing",
        "endpoints": {
            "/v1/agent/execute": "Execute agent task (requires x-wallet-private-key header)",
            "/v1/agent/chat": "Chat with agent (requires x-wallet-private-key header)",
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

    logger.info("Starting ATP Protocol + Swarms Integration API...")
    logger.info("Make sure to set OPENAI_API_KEY environment variable")
    logger.info(
        "Update recipient_pubkey in middleware configuration with your Solana wallet"
    )

    uvicorn.run(app, host="0.0.0.0", port=8000)

