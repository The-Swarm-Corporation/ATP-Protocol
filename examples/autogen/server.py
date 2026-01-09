"""
AutoGen + ATP Protocol Integration Example

This example demonstrates how to integrate ATP Protocol with AutoGen agents
to enable automatic payment processing for AutoGen-based services.

Installation:
    pip install pyautogen swarms atp-protocol fastapi uvicorn

Environment Variables:
    OPENAI_API_KEY="your-openai-api-key"
    # Optional: Configure ATP settings
    ATP_SETTLEMENT_URL="https://facilitator.swarms.world"
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger
import autogen
from typing import Dict, Any
from swarms import count_tokens

from atp.middleware import ATPSettlementMiddleware
from atp.schemas import PaymentToken

# Create FastAPI app
app = FastAPI(
    title="AutoGen + ATP Protocol Integration",
    description="Example API showing ATP payment processing with AutoGen agents",
)

# Model name for token counting
AGENT_MODEL = "gpt-4o-mini"

# AutoGen configuration
config_list = [
    {
        "model": AGENT_MODEL,
        "api_key": None,  # Will use OPENAI_API_KEY from environment
    }
]

# Initialize AutoGen agents
assistant = autogen.AssistantAgent(
    name="assistant",
    llm_config={
        "config_list": config_list,
        "temperature": 0.7,
    },
    system_message="You are a helpful AI assistant.",
)

user_proxy = autogen.UserProxyAgent(
    name="user_proxy",
    human_input_mode="NEVER",
    max_consecutive_auto_reply=10,
    code_execution_config=False,
)

# Add ATP Settlement Middleware
app.add_middleware(
    ATPSettlementMiddleware,
    allowed_endpoints=[
        "/v1/agent/chat",
        "/v1/agent/task",
    ],
    input_cost_per_million_usd=10.0,  # $10 per million input tokens
    output_cost_per_million_usd=30.0,  # $30 per million output tokens
    recipient_pubkey="YourSolanaWalletHere",  # Your wallet receives 95% of payments
    payment_token=PaymentToken.SOL,  # Use SOL for payments
    wallet_private_key_header="x-wallet-private-key",  # Header for client wallet key
    require_wallet=True,  # Require wallet key for payment
)


@app.post("/v1/agent/chat")
async def chat_with_agent(request: dict):
    """
    Chat with an AutoGen agent with automatic payment processing.

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

        # Execute the agent conversation
        logger.info(f"AutoGen chat request: {message[:100]}...")
        
        # Initiate chat with AutoGen
        chat_result = user_proxy.initiate_chat(
            assistant,
            message=message,
            max_turns=1,
        )

        # Count input tokens using Swarms tokenizer
        input_tokens = count_tokens(message, model=AGENT_MODEL)

        # Extract response from chat result
        # AutoGen stores messages in the agent's chat history
        response_text = ""
        if assistant.chat_messages:
            last_message = assistant.chat_messages[-1]
            if isinstance(last_message, dict):
                response_text = last_message.get("content", str(last_message))
            else:
                response_text = str(last_message)

        # Count output tokens using Swarms tokenizer
        output_tokens = count_tokens(response_text, model=AGENT_MODEL)

        # Return response with usage
        response_data = {
            "message": message,
            "response": response_text,
            "usage": {
                "input_tokens": int(input_tokens),
                "output_tokens": int(output_tokens),
                "total_tokens": int(input_tokens + output_tokens),
            },
        }

        return JSONResponse(content=response_data)

    except Exception as e:
        logger.error(f"AutoGen chat error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Chat failed: {str(e)}"
        )


@app.post("/v1/agent/task")
async def execute_task(request: dict):
    """
    Execute a task with AutoGen agents with automatic payment processing.

    Request:
        {
            "task": "Your task description here",
            "max_turns": 5  # Optional: maximum conversation turns
        }

    Response includes agent output and payment details.
    """
    try:
        task = request.get("task", "")
        if not task:
            raise HTTPException(
                status_code=400, detail="Task is required"
            )

        max_turns = request.get("max_turns", 5)

        # Count input tokens using Swarms tokenizer
        input_tokens = count_tokens(task, model=AGENT_MODEL)

        # Execute the agent task
        logger.info(f"Executing AutoGen task: {task[:100]}...")
        
        # Initiate task with AutoGen
        chat_result = user_proxy.initiate_chat(
            assistant,
            message=task,
            max_turns=max_turns,
        )

        # Extract final response
        response_text = ""
        if assistant.chat_messages:
            # Get the last assistant message
            for msg in reversed(assistant.chat_messages):
                if isinstance(msg, dict):
                    content = msg.get("content", "")
                    if content:
                        response_text = content
                        break
                else:
                    response_text = str(msg)
                    break

        # Count output tokens using Swarms tokenizer
        output_tokens = count_tokens(response_text, model=AGENT_MODEL)

        # Return response with usage data
        response_data = {
            "output": response_text,
            "task": task,
            "usage": {
                "input_tokens": int(input_tokens),
                "output_tokens": int(output_tokens),
                "total_tokens": int(input_tokens + output_tokens),
            },
        }

        return JSONResponse(content=response_data)

    except Exception as e:
        logger.error(f"AutoGen task execution error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Task execution failed: {str(e)}"
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
        "framework": "autogen",
    }


@app.get("/")
async def root():
    """
    Root endpoint with API information.
    """
    return {
        "name": "AutoGen + ATP Protocol Integration",
        "description": "API for AutoGen agents with automatic payment processing",
        "endpoints": {
            "/v1/agent/chat": "Chat with agent (requires x-wallet-private-key header)",
            "/v1/agent/task": "Execute agent task (requires x-wallet-private-key header)",
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

    logger.info("Starting AutoGen + ATP Protocol Integration API...")
    logger.info("Make sure to set OPENAI_API_KEY environment variable")
    logger.info(
        "Update recipient_pubkey in middleware configuration with your Solana wallet"
    )

    uvicorn.run(app, host="0.0.0.0", port=8000)

