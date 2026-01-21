"""
CrewAI + ATP Protocol Integration Example

This example demonstrates how to integrate ATP Protocol with CrewAI agents
to enable automatic payment processing for CrewAI-based services.

Installation:
    pip install crewai swarms atp-protocol fastapi uvicorn

Environment Variables:
    OPENAI_API_KEY="your-openai-api-key"
    # Optional: Configure ATP settings
    ATP_SETTLEMENT_URL="https://facilitator.swarms.world"
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger
from crewai import Agent, Task, Crew
from swarms import count_tokens

from atp.middleware import ATPSettlementMiddleware
from atp.schemas import PaymentToken

# Create FastAPI app
app = FastAPI(
    title="CrewAI + ATP Protocol Integration",
    description="Example API showing ATP payment processing with CrewAI agents",
)

# Model name for token counting
AGENT_MODEL = "gpt-4o-mini"

# Initialize CrewAI agents
researcher = Agent(
    role="Research Analyst",
    goal="Conduct thorough research on given topics",
    backstory="You are an expert research analyst with years of experience in gathering and analyzing information.",
    verbose=True,
    allow_delegation=False,
)

writer = Agent(
    role="Content Writer",
    goal="Create engaging and informative content based on research",
    backstory="You are a skilled content writer who transforms research into compelling narratives.",
    verbose=True,
    allow_delegation=False,
)

# Add ATP Settlement Middleware
app.add_middleware(
    ATPSettlementMiddleware,
    allowed_endpoints=[
        "/v1/crew/execute",
        "/v1/crew/research",
    ],
    input_cost_per_million_usd=10.0,  # $10 per million input tokens
    output_cost_per_million_usd=30.0,  # $30 per million output tokens
    recipient_pubkey="YourSolanaWalletHere",  # Your wallet receives 95% of payments
    payment_token=PaymentToken.SOL,  # Use SOL for payments
    wallet_private_key_header="x-wallet-private-key",  # Header for client wallet key
    require_wallet=True,  # Require wallet key for payment
)


@app.post("/v1/crew/execute")
async def execute_crew(request: dict):
    """
    Execute a CrewAI crew task with automatic payment processing.

    Request:
        {
            "task": "Your task description here",
            "agent_role": "researcher"  # Optional: "researcher" or "writer"
        }

    Response includes crew output and payment details.
    """
    try:
        task_description = request.get("task", "")
        if not task_description:
            raise HTTPException(
                status_code=400, detail="Task is required"
            )

        agent_role = request.get("agent_role", "researcher")
        selected_agent = researcher if agent_role == "researcher" else writer

        # Create a task
        task = Task(
            description=task_description,
            agent=selected_agent,
        )

        # Count input tokens using Swarms tokenizer
        input_tokens = count_tokens(task_description, model=AGENT_MODEL)

        # Create and execute crew
        logger.info(f"Executing CrewAI task: {task_description[:100]}...")
        crew = Crew(
            agents=[selected_agent],
            tasks=[task],
            verbose=True,
        )

        result = crew.kickoff()

        # Count output tokens using Swarms tokenizer
        output_tokens = count_tokens(str(result), model=AGENT_MODEL)

        # Return response with usage data
        response_data = {
            "output": str(result),
            "task": task_description,
            "usage": {
                "input_tokens": int(input_tokens),
                "output_tokens": int(output_tokens),
                "total_tokens": int(input_tokens + output_tokens),
            },
        }

        return JSONResponse(content=response_data)

    except Exception as e:
        logger.error(f"CrewAI execution error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Crew execution failed: {str(e)}"
        )


@app.post("/v1/crew/research")
async def research_task(request: dict):
    """
    Execute a research task with CrewAI crew (multi-agent workflow).

    Request:
        {
            "topic": "Research topic here",
            "output_format": "article"  # Optional: "article" or "summary"
        }

    Response includes research output and payment details.
    """
    try:
        topic = request.get("topic", "")
        if not topic:
            raise HTTPException(
                status_code=400, detail="Topic is required"
            )

        output_format = request.get("output_format", "article")

        # Build full input text for token counting
        full_input = f"Research and analyze: {topic}. Write a {output_format} based on the research findings."
        
        # Count input tokens using Swarms tokenizer
        input_tokens = count_tokens(full_input, model=AGENT_MODEL)

        # Create research task
        research_task_obj = Task(
            description=f"Research and analyze: {topic}",
            agent=researcher,
            expected_output="A comprehensive research report with key findings and insights",
        )

        # Create writing task
        writing_task_obj = Task(
            description=f"Write a {output_format} based on the research findings about: {topic}",
            agent=writer,
            expected_output=f"A well-structured {output_format} that presents the research findings clearly",
        )

        # Create and execute crew with multiple agents
        logger.info(f"Executing CrewAI research task: {topic[:100]}...")
        crew = Crew(
            agents=[researcher, writer],
            tasks=[research_task_obj, writing_task_obj],
            verbose=True,
        )

        result = crew.kickoff()

        # Count output tokens using Swarms tokenizer
        output_tokens = count_tokens(str(result), model=AGENT_MODEL)

        # Return response with usage data
        response_data = {
            "output": str(result),
            "topic": topic,
            "usage": {
                "input_tokens": int(input_tokens),
                "output_tokens": int(output_tokens),
                "total_tokens": int(input_tokens + output_tokens),
            },
        }

        return JSONResponse(content=response_data)

    except Exception as e:
        logger.error(f"CrewAI research error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Research task failed: {str(e)}"
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
        "framework": "crewai",
    }


@app.get("/")
async def root():
    """
    Root endpoint with API information.
    """
    return {
        "name": "CrewAI + ATP Protocol Integration",
        "description": "API for CrewAI agents with automatic payment processing",
        "endpoints": {
            "/v1/crew/execute": "Execute crew task (requires x-wallet-private-key header)",
            "/v1/crew/research": "Execute research task with multi-agent workflow (requires x-wallet-private-key header)",
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

    logger.info("Starting CrewAI + ATP Protocol Integration API...")
    logger.info("Make sure to set OPENAI_API_KEY environment variable")
    logger.info(
        "Update recipient_pubkey in middleware configuration with your Solana wallet"
    )

    uvicorn.run(app, host="0.0.0.0", port=8000)

