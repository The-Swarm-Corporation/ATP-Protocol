# ATP Protocol Examples

This directory contains comprehensive examples demonstrating how to integrate **ATP Protocol** with various AI agent frameworks and APIs to enable automatic payment processing.

## Overview

Each example shows how to:
- Set up a FastAPI server with ATP middleware
- Integrate with different AI agent frameworks
- Process automatic Solana payments based on token usage
- Handle wallet authentication and settlement

## Examples Directory Structure

### Framework Integration Examples

| Framework | Directory | Server | Client | Documentation |
|-----------|-----------|--------|--------|---------------|
| **LangChain** | [`langchain/`](./langchain/) | [`server.py`](./langchain/server.py) | [`client.py`](./langchain/client.py) | [`README.md`](./langchain/README.md) |
| **AutoGen** | [`autogen/`](./autogen/) | [`server.py`](./autogen/server.py) | [`client.py`](./autogen/client.py) | [`README.md`](./autogen/README.md) |
| **CrewAI** | [`crewai/`](./crewai/) | [`server.py`](./crewai/server.py) | [`client.py`](./crewai/client.py) | [`README.md`](./crewai/README.md) |
| **Anthropic API** | [`anthropic/`](./anthropic/) | [`server.py`](./anthropic/server.py) | [`client.py`](./anthropic/client.py) | [`README.md`](./anthropic/README.md) |

### Standalone Examples

| Example | File | Description |
|---------|------|-------------|
| **Swarms Integration** | [`example.py`](./example.py) | Complete Swarms framework integration example |
| **Full Flow Example** | [`full_flow_example.py`](./full_flow_example.py) | End-to-end payment flow demonstration |
| **Settlement Service** | [`settlement_service_example.py`](./settlement_service_example.py) | Direct settlement service usage example |
| **Client Smoke Test** | [`client_smoke_test.py`](./client_smoke_test.py) | Client testing and validation |

## Quick Start

### 1. Choose Your Framework

Select the framework you want to integrate:

- **[LangChain](./langchain/)** - Popular Python framework for building LLM applications
- **[AutoGen](./autogen/)** - Microsoft's multi-agent conversation framework
- **[CrewAI](./crewai/)** - Multi-agent orchestration framework
- **[Anthropic API](./anthropic/)** - Direct integration with Claude API

### 2. Install Dependencies

Each example folder contains its own requirements. Navigate to the example directory and install:

```bash
cd examples/[framework-name]
pip install -r requirements.txt  # If available
# Or install manually based on the example's README
```

### 3. Configure Environment

Create a `.env` file in the example directory:

```bash
# Required: API key for your chosen framework
OPENAI_API_KEY="your-key"  # For LangChain, AutoGen, CrewAI
ANTHROPIC_API_KEY="your-key"  # For Anthropic

# Required: Solana wallet private key (for client)
ATP_PRIVATE_KEY="[1,2,3,...]"  # JSON array format or base58 string

# Optional: ATP Settlement Service URL
ATP_SETTLEMENT_URL="https://facilitator.swarms.world"
```

### 4. Update Server Configuration

Edit `server.py` and update the `recipient_pubkey`:

```python
app.add_middleware(
    ATPSettlementMiddleware,
    recipient_pubkey="YourSolanaWalletHere",  # ← Update this!
    # ... other config
)
```

### 5. Run the Server

```bash
python server.py
```

### 6. Test with Client

In another terminal:

```bash
python client.py
```

## Framework-Specific Guides

### LangChain Integration

**[📁 langchain/](./langchain/)**

Integrate ATP Protocol with LangChain agents and tools.

**Features:**
- LangChain agent execution with automatic payment
- Tool integration (calculator example)
- Conversational chat interface
- Token usage tracking

**See:** [LangChain README](./langchain/README.md)

### AutoGen Integration

**[📁 autogen/](./autogen/)**

Integrate ATP Protocol with AutoGen multi-agent conversations.

**Features:**
- Multi-agent conversation support
- Task execution with configurable turns
- Agent delegation and collaboration
- Token usage tracking

**See:** [AutoGen README](./autogen/README.md)

### CrewAI Integration

**[📁 crewai/](./crewai/)**

Integrate ATP Protocol with CrewAI multi-agent crews.

**Features:**
- Multi-agent crew workflows
- Research and writing task pipelines
- Agent role specialization
- Token usage tracking

**See:** [CrewAI README](./crewai/README.md)

### Anthropic API Integration

**[📁 anthropic/](./anthropic/)**

Integrate ATP Protocol with Anthropic's Claude API.

**Features:**
- Native Anthropic Messages API support
- OpenAI-compatible chat completions
- Actual token usage from API responses
- Multi-turn conversation support

**See:** [Anthropic README](./anthropic/README.md)

## Common Patterns

All examples follow similar patterns:

### 1. Server Setup

```python
from fastapi import FastAPI
from atp.middleware import ATPSettlementMiddleware
from atp.schemas import PaymentToken

app = FastAPI()

app.add_middleware(
    ATPSettlementMiddleware,
    allowed_endpoints=["/v1/agent/run"],
    input_cost_per_million_usd=10.0,
    output_cost_per_million_usd=30.0,
    recipient_pubkey="YourSolanaWalletHere",
    payment_token=PaymentToken.SOL,
)
```

### 2. Usage Tracking

Return usage data in your endpoint responses:

```python
@app.post("/v1/agent/run")
async def run_agent(request: dict):
    # ... execute agent ...
    
    return {
        "output": result,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
    }
```

### 3. Client Authentication

Include wallet private key in headers:

```python
headers = {
    "Content-Type": "application/json",
    "x-wallet-private-key": WALLET_PRIVATE_KEY,
}
```

## Payment Details

All examples use the same payment structure:

- **Input tokens**: $10 per million tokens
- **Output tokens**: $30 per million tokens
- **Payment split**: 95% to your wallet, 5% to Swarms Treasury
- **Payment token**: SOL (configurable to USDC)

## Testing

Each example includes:

1. **Server** (`server.py`) - FastAPI server with ATP middleware
2. **Client** (`client.py`) - Example client with wallet authentication
3. **Health Check** - Endpoint to verify server status

### Running Tests

```bash
# Start server
python server.py

# In another terminal, run client
python client.py
```

## Troubleshooting

### Common Issues

1. **Missing wallet key**: Ensure `ATP_PRIVATE_KEY` is set in `.env`
2. **Invalid recipient pubkey**: Update `recipient_pubkey` in `server.py`
3. **API key errors**: Verify your framework's API key is set correctly
4. **Payment failures**: Check Solana wallet has sufficient balance

### Getting Help

- Check the framework-specific README in each example folder
- Review the main [ATP Protocol README](../README.md)
- Verify environment variables are set correctly

## Next Steps

After running an example:

1. Customize the agent configuration for your use case
2. Implement proper token tracking (use actual API responses when available)
3. Add authentication/authorization layers
4. Configure custom pricing rates
5. Deploy to production

## Resources

- [ATP Protocol Documentation](../README.md)
- [Swarms Framework](https://github.com/kyegomez/swarms)
- [LangChain Documentation](https://python.langchain.com/)
- [AutoGen Documentation](https://microsoft.github.io/autogen/)
- [CrewAI Documentation](https://docs.crewai.com/)
- [Anthropic API Documentation](https://docs.anthropic.com/)

