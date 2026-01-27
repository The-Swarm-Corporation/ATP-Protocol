# Swarms Framework + ATP Protocol Integration

This example demonstrates how to integrate **ATP Protocol** with **Swarms** agents to enable automatic payment processing for Swarms-based AI services.

## Overview

This integration allows you to:
- Run Swarms agents with automatic Solana payment processing
- Charge users based on token usage (input/output tokens)
- Receive payments directly to your Solana wallet
- Use ATP middleware to handle all payment logic automatically

## Installation

```bash
# Install required packages
pip install swarms atp-protocol fastapi uvicorn httpx python-dotenv

# Or install from requirements
pip install -r requirements.txt
```

## Environment Setup

Create a `.env` file in this directory:

```bash
# Required: OpenAI API key for Swarms
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
    allowed_endpoints=["/v1/agent/execute", "/v1/agent/chat"],
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

### 1. Execute Agent Task

**POST** `/v1/agent/execute`

Execute a Swarms agent task with automatic payment processing.

**Request:**
```json
{
    "task": "What are the key benefits of using a multi-agent system?",
    "system_prompt": "You are a helpful AI assistant."
}
```

**Response:**
```json
{
    "output": "Multi-agent systems offer several key benefits...",
    "task": "What are the key benefits of using a multi-agent system?",
    "usage": {
        "input_tokens": 25,
        "output_tokens": 150,
        "total_tokens": 175
    },
    "atp_settlement": {
        "status": "paid",
        "transaction_signature": "5j7s8K9...",
        "payment": {
            "total_amount_sol": 0.00525,
            "recipient": {"amount_sol": 0.0049875},
            "treasury": {"amount_sol": 0.0002625}
        }
    }
}
```

### 2. Chat with Agent

**POST** `/v1/agent/chat`

Chat with a Swarms agent (conversational interface).

**Request:**
```json
{
    "message": "Explain the concept of agentic AI in simple terms.",
    "conversation_history": []  # Optional
}
```

**Response:**
```json
{
    "message": "Explain the concept of agentic AI in simple terms.",
    "response": "Agentic AI refers to AI systems that can act autonomously...",
    "usage": {
        "input_tokens": 15,
        "output_tokens": 100,
        "total_tokens": 115
    },
    "atp_settlement": {
        "status": "paid",
        "transaction_signature": "5j7s8K9...",
        "payment": {
            "total_amount_sol": 0.00345,
            "recipient": {"amount_sol": 0.0032775},
            "treasury": {"amount_sol": 0.0001725}
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
    "framework": "swarms"
}
```

## How It Works

1. **Client sends request** with wallet private key in `x-wallet-private-key` header
2. **ATP middleware intercepts** the request and forwards it to your endpoint
3. **Swarms agent executes** the task and returns a response
4. **Usage data is extracted** from the response (token counts using Swarms' `count_tokens`)
5. **ATP middleware calculates** payment based on token usage
6. **Payment is processed** on Solana (95% to you, 5% to Swarms Treasury)
7. **Response includes** settlement details with transaction signature

## Payment Details

- **Input tokens**: $10 per million tokens
- **Output tokens**: $30 per million tokens
- **Payment split**: 95% to your wallet, 5% to Swarms Treasury
- **Payment token**: SOL (configurable to USDC)

## Usage Tracking

This example uses **Swarms' `count_tokens` function** for accurate token counting:

```python
from swarms import count_tokens

# Count input tokens
input_tokens = count_tokens(task, model=AGENT_MODEL)

# Count output tokens
output_tokens = count_tokens(str(result), model=AGENT_MODEL)
```

This provides accurate token counts that match the actual LLM usage, ensuring fair billing.

## Agent Configuration

You can customize the Swarms agent configuration:

```python
agent = Agent(
    model_name="gpt-4o-mini",
    max_loops="auto",  # or specific number
    interactive=False,
    temperature=0.7,  # Optional
    system_prompt="Custom system prompt",  # Optional
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

- Customize the agent with your own system prompts and configurations
- Add tools and capabilities to the agent
- Implement conversation history management
- Configure custom pricing rates
- Add authentication/authorization layers
- Deploy to production

## Resources

- [Swarms Framework](https://github.com/kyegomez/swarms)
- [Swarms Documentation](https://docs.swarms.world)
- [ATP Protocol Documentation](../README.md)

