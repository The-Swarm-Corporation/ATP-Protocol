# AutoGen + ATP Protocol Integration

This example demonstrates how to integrate **ATP Protocol** with **AutoGen** agents to enable automatic payment processing for AutoGen-based AI services.

## Overview

This integration allows you to:
- Run AutoGen multi-agent conversations with automatic Solana payment processing
- Charge users based on token usage (input/output tokens)
- Receive payments directly to your Solana wallet
- Use ATP middleware to handle all payment logic automatically

## Installation

```bash
# Install required packages
pip install pyautogen atp-protocol fastapi uvicorn httpx python-dotenv

# Or install from requirements
pip install -r requirements.txt
```

## Environment Setup

Create a `.env` file in this directory:

```bash
# Required: OpenAI API key for AutoGen
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
    allowed_endpoints=["/v1/agent/chat", "/v1/agent/task"],
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

### 1. Chat with Agent

**POST** `/v1/agent/chat`

Chat with an AutoGen agent (conversational interface).

**Request:**
```json
{
    "message": "What are the key benefits of multi-agent systems?",
    "conversation_history": []  # Optional
}
```

**Response:**
```json
{
    "message": "What are the key benefits of multi-agent systems?",
    "response": "Multi-agent systems offer several key benefits...",
    "usage": {
        "input_tokens": 12,
        "output_tokens": 150,
        "total_tokens": 162
    },
    "atp_settlement": {
        "status": "paid",
        "transaction_signature": "5j7s8K9...",
        "payment": {
            "total_amount_sol": 0.00486,
            "recipient": {"amount_sol": 0.004617},
            "treasury": {"amount_sol": 0.000243}
        }
    }
}
```

### 2. Execute Agent Task

**POST** `/v1/agent/task`

Execute a task with AutoGen agents (multi-turn conversation).

**Request:**
```json
{
    "task": "Explain the concept of agentic AI and provide 3 real-world use cases.",
    "max_turns": 3
}
```

**Response:**
```json
{
    "output": "Agentic AI refers to AI systems that can act autonomously...",
    "task": "Explain the concept of agentic AI and provide 3 real-world use cases.",
    "usage": {
        "input_tokens": 20,
        "output_tokens": 300,
        "total_tokens": 320
    },
    "atp_settlement": {
        "status": "paid",
        "transaction_signature": "5j7s8K9...",
        "payment": {
            "total_amount_sol": 0.0096,
            "recipient": {"amount_sol": 0.00912},
            "treasury": {"amount_sol": 0.00048}
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
    "framework": "autogen"
}
```

## How It Works

1. **Client sends request** with wallet private key in `x-wallet-private-key` header
2. **ATP middleware intercepts** the request and forwards it to your endpoint
3. **AutoGen agents execute** the task through multi-agent conversation
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

1. Use AutoGen's LLM callbacks to track actual token usage
2. Implement proper token counting from LLM responses
3. Use the `autogen.agentchat.contrib.cost` module to capture usage data

Example with cost tracking:
```python
from autogen.agentchat.contrib.cost import track_cost

with track_cost() as cost_tracker:
    chat_result = user_proxy.initiate_chat(
        assistant,
        message=task,
        max_turns=max_turns,
    )
    usage = {
        "input_tokens": cost_tracker.total_input_tokens,
        "output_tokens": cost_tracker.total_output_tokens,
        "total_tokens": cost_tracker.total_tokens,
    }
```

## Multi-Agent Configuration

You can extend this example to use multiple agents:

```python
# Create specialized agents
researcher = autogen.AssistantAgent(
    name="researcher",
    llm_config={"config_list": config_list},
    system_message="You are a research specialist.",
)

analyst = autogen.AssistantAgent(
    name="analyst",
    llm_config={"config_list": config_list},
    system_message="You are a data analyst.",
)

# Create a group chat
groupchat = autogen.GroupChat(
    agents=[user_proxy, researcher, analyst],
    messages=[],
    max_round=10,
)

manager = autogen.GroupChatManager(
    groupchat=groupchat,
    llm_config={"config_list": config_list},
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
- Implement proper token tracking using AutoGen callbacks
- Add multi-agent group chat functionality
- Configure custom pricing rates
- Add authentication/authorization layers
- Implement conversation history management

## Resources

- [AutoGen Documentation](https://microsoft.github.io/autogen/)
- [ATP Protocol Documentation](../README.md)
- [Swarms Framework](https://github.com/kyegomez/swarms)

