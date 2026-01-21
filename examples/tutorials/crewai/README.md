# CrewAI + ATP Protocol Integration

This example demonstrates how to integrate **ATP Protocol** with **CrewAI** agents to enable automatic payment processing for CrewAI-based AI services.

## Overview

This integration allows you to:
- Run CrewAI multi-agent crews with automatic Solana payment processing
- Charge users based on token usage (input/output tokens)
- Receive payments directly to your Solana wallet
- Use ATP middleware to handle all payment logic automatically

## Installation

```bash
# Install required packages
pip install crewai atp-protocol fastapi uvicorn httpx python-dotenv

# Or install from requirements
pip install -r requirements.txt
```

## Environment Setup

Create a `.env` file in this directory:

```bash
# Required: OpenAI API key for CrewAI
OPENAI_API_KEY="your-openai-api-key"

# Required: Solana wallet private key (for client)
ATP_PRIVATE_KEY="[1,2,3,...]"  # JSON array format or base58 string

# Optional: ATP Settlement Service URL
ATP_SETTLEMENT_URL="https://facilitator.swarms.world"
```

## Configuration

Before running the server, update the `recipient_pubkey` in `server.py`:

```python
app.add_middleware(
    ATPSettlementMiddleware,
    allowed_endpoints=["/v1/crew/execute", "/v1/crew/research"],
    input_cost_per_million_usd=10.0,
    output_cost_per_million_usd=30.0,
    recipient_pubkey="YourSolanaWalletHere",  # ← Update this!
    payment_token=PaymentToken.SOL,
    wallet_private_key_header="x-wallet-private-key",
    require_wallet=True,
)
```

Replace `"YourSolanaWalletHere"` with your actual Solana wallet public key (the address that will receive payments).

## Running the Server

```bash
python server.py
```

The server will start on `http://localhost:8000`.

## Running the Client

```bash
python client.py
```

## API Endpoints

### 1. Execute Crew Task

**POST** `/v1/crew/execute`

Execute a task with a CrewAI crew (single agent).

**Request:**
```json
{
    "task": "Research the latest developments in AI agent frameworks",
    "agent_role": "researcher"
}
```

**Response:**
```json
{
    "output": "Based on my research, the latest developments in AI agent frameworks include...",
    "task": "Research the latest developments in AI agent frameworks",
    "usage": {
        "input_tokens": 15,
        "output_tokens": 250,
        "total_tokens": 265
    },
    "atp_settlement": {
        "status": "paid",
        "transaction_signature": "5j7s8K9...",
        "payment": {
            "total_amount_sol": 0.00795,
            "recipient": {"amount_sol": 0.0075525},
            "treasury": {"amount_sol": 0.0003975}
        }
    }
}
```

### 2. Research Task (Multi-Agent)

**POST** `/v1/crew/research`

Execute a research task with a multi-agent CrewAI crew (researcher + writer).

**Request:**
```json
{
    "topic": "The future of autonomous AI agents in enterprise applications",
    "output_format": "article"
}
```

**Response:**
```json
{
    "output": "The future of autonomous AI agents in enterprise applications...",
    "topic": "The future of autonomous AI agents in enterprise applications",
    "usage": {
        "input_tokens": 30,
        "output_tokens": 500,
        "total_tokens": 530
    },
    "atp_settlement": {
        "status": "paid",
        "transaction_signature": "5j7s8K9...",
        "payment": {
            "total_amount_sol": 0.0159,
            "recipient": {"amount_sol": 0.015105},
            "treasury": {"amount_sol": 0.000795}
        }
    }
}
```

### 3. Health Check

**GET** `/v1/health`

Check server health (no payment required).

**Response:**
```json
{
    "status": "healthy",
    "agent_ready": true,
    "atp_middleware": "active",
    "framework": "crewai"
}
```

## How It Works

1. **Client sends request** with wallet private key in `x-wallet-private-key` header
2. **ATP middleware intercepts** the request and forwards it to your endpoint
3. **CrewAI crew executes** the task through multi-agent collaboration
4. **Usage data is extracted** from the response (token counts)
5. **ATP middleware calculates** payment based on token usage
6. **Payment is processed** on Solana (95% to you, 5% to Swarms Treasury)
7. **Response includes** settlement details with transaction signature

## Payment Details

- **Input tokens**: $10 per million tokens
- **Output tokens**: $30 per million tokens
- **Payment split**: 95% to your wallet, 5% to Swarms Treasury
- **Payment token**: SOL (configurable to USDC)

## Usage Tracking

The example uses token estimation for simplicity. In production, you should:

1. Use CrewAI's LLM callbacks to track actual token usage
2. Implement proper token counting from LLM responses
3. Use the `crewai.tools` module to capture usage data

Example with proper tracking:
```python
from crewai import LLM

# Configure LLM with callback
llm = LLM(
    model="gpt-4o-mini",
    callbacks=[your_token_tracking_callback],
)

# Use in agents
researcher = Agent(
    role="Research Analyst",
    llm=llm,
    # ... other config
)
```

## Multi-Agent Crews

CrewAI excels at multi-agent workflows. You can create complex crews:

```python
# Create specialized agents
researcher = Agent(
    role="Research Analyst",
    goal="Conduct thorough research",
    backstory="Expert researcher",
)

analyst = Agent(
    role="Data Analyst",
    goal="Analyze data and extract insights",
    backstory="Expert data analyst",
)

writer = Agent(
    role="Content Writer",
    goal="Create compelling content",
    backstory="Skilled writer",
)

# Create tasks
research_task = Task(
    description="Research topic X",
    agent=researcher,
)

analysis_task = Task(
    description="Analyze research findings",
    agent=analyst,
    context=[research_task],  # Depends on research
)

writing_task = Task(
    description="Write article based on analysis",
    agent=writer,
    context=[analysis_task],  # Depends on analysis
)

# Create crew
crew = Crew(
    agents=[researcher, analyst, writer],
    tasks=[research_task, analysis_task, writing_task],
    verbose=True,
)
```

## Error Handling

- **Missing wallet key**: Returns `401 Unauthorized`
- **Missing usage data**: Logs warning and returns original response
- **Payment failure**: Returns `500 Internal Server Error` with details
- **Invalid private key**: Returns `500 Internal Server Error` with parsing error

## Security Considerations

- Private keys are only used in-memory during each request
- Keys are never persisted or logged
- All settlement logic is handled by the ATP Settlement Service
- Transactions are verified before responses are returned

## Next Steps

- Customize agents with specialized roles and capabilities
- Implement proper token tracking using CrewAI callbacks
- Add more complex multi-agent workflows
- Configure custom pricing rates
- Add authentication/authorization layers
- Implement task dependencies and workflows

## Resources

- [CrewAI Documentation](https://docs.crewai.com/)
- [ATP Protocol Documentation](../README.md)
- [Swarms Framework](https://github.com/kyegomez/swarms)

