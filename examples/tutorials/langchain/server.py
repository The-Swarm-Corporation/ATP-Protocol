"""
LangChain + ATP Protocol Integration Example

This example demonstrates how to integrate ATP Protocol with LangChain agents
to enable automatic payment processing for LangChain-based services.

Installation:
    pip install langchain langchain-openai swarms atp-protocol fastapi uvicorn

Environment Variables:
    OPENAI_API_KEY="your-openai-api-key"
    # Optional: Configure ATP settings
    ATP_SETTLEMENT_URL="https://facilitator.swarms.world"
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger
from langchain_openai import ChatOpenAI
from langchain.agents import initialize_agent, AgentType
from langchain.tools import Tool
from langchain.schema import HumanMessage
from swarms import count_tokens

from atp.middleware import ATPSettlementMiddleware
from atp.schemas import PaymentToken

# Create FastAPI app
app = FastAPI(
    title="LangChain + ATP Protocol Integration",
    description="Example API showing ATP payment processing with LangChain agents",
)

# Model name for token counting
AGENT_MODEL = "gpt-4o-mini"

# Initialize LangChain LLM
llm = ChatOpenAI(
    model=AGENT_MODEL,
    temperature=0.7,
)

# Define a simple tool for the agent
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression."""
    try:
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"Error: {str(e)}"

# Create tools
tools = [
    Tool(
        name="Calculator",
        func=calculate,
        description="Useful for performing mathematical calculations. Input should be a valid Python expression.",
    )
]

# Initialize LangChain agent
agent = initialize_agent(
    tools=tools,
    llm=llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True,
)

# Add ATP Settlement Middleware
app.add_middleware(
    ATPSettlementMiddleware,
    allowed_endpoints=[
        "/v1/agent/run",
        "/v1/agent/chat",
    ],
    input_cost_per_million_usd=10.0,  # $10 per million input tokens
    output_cost_per_million_usd=30.0,  # $30 per million output tokens
    recipient_pubkey="YourSolanaWalletHere",  # Your wallet receives 95% of payments
    payment_token=PaymentToken.SOL,  # Use SOL for payments
    wallet_private_key_header="x-wallet-private-key",  # Header for client wallet key
    require_wallet=True,  # Require wallet key for payment
)


@app.post("/v1/agent/run")
async def run_agent(request: dict):
    """
    Execute a LangChain agent task with automatic payment processing.

    Request:
        {
            "task": "Your task description here",
            "input": "What is 25 * 37?"
        }

    Response includes:
        - Agent output
        - Usage data (for billing)
        - ATP settlement information (payment details)
    """
    try:
        # Extract task from request
        task = request.get("task") or request.get("input", "")
        if not task:
            raise HTTPException(
                status_code=400, detail="Task or input is required"
            )

        # Count input tokens using Swarms tokenizer
        input_tokens = count_tokens(task, model=AGENT_MODEL)

        # Execute the agent
        logger.info(f"Executing LangChain agent task: {task[:100]}...")
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
                "input_tokens": int(input_tokens),
                "output_tokens": int(output_tokens),
                "total_tokens": int(input_tokens + output_tokens),
            },
        }

        return JSONResponse(content=response_data)

    except Exception as e:
        logger.error(f"LangChain agent execution error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Agent execution failed: {str(e)}"
        )


@app.post("/v1/agent/chat")
async def chat_with_agent(request: dict):
    """
    Chat with a LangChain agent (conversational interface).

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

        # Build messages from history
        messages = []
        for h in history:
            if "user" in h:
                messages.append(HumanMessage(content=h["user"]))
            if "assistant" in h:
                messages.append(h["assistant"])  # Assuming it's already a message object

        # Add current message
        messages.append(HumanMessage(content=message))

        # Build full input text for token counting
        full_input = message
        if messages:
            full_input = "\n".join([str(m.content) for m in messages])

        # Count input tokens using Swarms tokenizer
        input_tokens = count_tokens(full_input, model=AGENT_MODEL)

        # Execute agent with messages
        logger.info(f"Chat request: {message[:100]}...")
        if messages:
            response = llm.invoke(messages)
            result = response.content
        else:
            result = agent.run(message)

        # Count output tokens using Swarms tokenizer
        output_tokens = count_tokens(str(result), model=AGENT_MODEL)

        # Return response with usage
        response_data = {
            "message": message,
            "response": result,
            "usage": {
                "input_tokens": int(input_tokens),
                "output_tokens": int(output_tokens),
                "total_tokens": int(input_tokens + output_tokens),
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
        "framework": "langchain",
    }


@app.get("/")
async def root():
    """
    Root endpoint with API information.
    """
    return {
        "name": "LangChain + ATP Protocol Integration",
        "description": "API for LangChain agents with automatic payment processing",
        "endpoints": {
            "/v1/agent/run": "Execute agent task (requires x-wallet-private-key header)",
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

    logger.info("Starting LangChain + ATP Protocol Integration API...")
    logger.info("Make sure to set OPENAI_API_KEY environment variable")
    logger.info(
        "Update recipient_pubkey in middleware configuration with your Solana wallet"
    )

    uvicorn.run(app, host="0.0.0.0", port=8000)

