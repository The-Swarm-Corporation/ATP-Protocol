# LangChain + ATP Protocol Integration

This example demonstrates how to integrate **ATP Protocol** with **LangChain** agents to enable automatic payment processing for LangChain-based AI services.

## Overview

This integration allows you to:
- Run LangChain agents with automatic Solana payment processing
- Charge users based on token usage (input/output tokens)
- Receive payments directly to your Solana wallet
- Use ATP middleware to handle all payment logic automatically

## Installation

```bash
# Install required packages
pip install langchain langchain-openai atp-protocol fastapi uvicorn httpx python-dotenv

# Or install from requirements
pip install -r requirements.txt
```

## Environment Setup

Create a `.env` file in this directory:

```bash
# Required: OpenAI API key for LangChain
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
    allowed_endpoints=["/v1/agent/run", "/v1/agent/chat"],
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

**POST** `/v1/agent/run`

Execute a LangChain agent with tools.

**Request:**
```json
{
    "task": "What is 25 * 37? Use the calculator tool.",
    "input": "Calculate 25 * 37"
}
```

**Response:**
```json
{
    "output": "925",
    "task": "What is 25 * 37? Use the calculator tool.",
    "usage": {
        "input_tokens": 15,
        "output_tokens": 5,
        "total_tokens": 20
    },
    "atp_settlement": {
        "status": "paid",
        "transaction_signature": "5j7s8K9...",
        "payment": {
            "total_amount_sol": 0.0003,
            "recipient": {"amount_sol": 0.000285},
            "treasury": {"amount_sol": 0.000015}
        }
    },
    "atp_usage": {
        "input_tokens": 15,
        "output_tokens": 5,
        "total_tokens": 20
    }
}
```

### 2. Chat with Agent

**POST** `/v1/agent/chat`

Chat with a LangChain agent (conversational interface).

**Request:**
```json
{
    "message": "What is the square root of 144?",
    "conversation_history": []  # Optional
}
```

**Response:**
```json
{
    "message": "What is the square root of 144?",
    "response": "The square root of 144 is 12.",
    "usage": {
        "input_tokens": 10,
        "output_tokens": 8,
        "total_tokens": 18
    },
    "atp_settlement": {
        "status": "paid",
        "transaction_signature": "5j7s8K9...",
        "payment": {
            "total_amount_sol": 0.00027,
            "recipient": {"amount_sol": 0.0002565},
            "treasury": {"amount_sol": 0.0000135}
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
    "framework": "langchain"
}
```

## How It Works

1. **Client sends request** with wallet private key in `x-wallet-private-key` header
2. **ATP middleware intercepts** the request and forwards it to your endpoint
3. **LangChain agent executes** the task and returns a response
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

1. Use LangChain callbacks to track actual token usage
2. Implement proper token counting from LLM responses
3. Use the `langchain.callbacks` module to capture usage data

Example with callbacks:
```python
from langchain.callbacks import get_openai_callback

with get_openai_callback() as cb:
    result = agent.run(task)
    usage = {
        "input_tokens": cb.prompt_tokens,
        "output_tokens": cb.completion_tokens,
        "total_tokens": cb.total_tokens,
    }
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

- Customize the agent with your own tools and prompts
- Implement proper token tracking using LangChain callbacks
- Add conversation history management
- Configure custom pricing rates
- Add authentication/authorization layers

## Resources

- [LangChain Documentation](https://python.langchain.com/)
- [ATP Protocol Documentation](../README.md)
- [Swarms Framework](https://github.com/kyegomez/swarms)

