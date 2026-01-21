# ATP Protocol Examples

This directory contains comprehensive examples demonstrating how to integrate **ATP Protocol** with various AI agent frameworks and APIs to enable automatic payment processing.

## Directory Structure

```
examples/
├── tutorials/          # Framework integration tutorials
│   ├── swarms/        # Swarms framework integration
│   ├── langchain/     # LangChain framework integration
│   ├── autogen/       # AutoGen framework integration
│   ├── crewai/        # CrewAI framework integration
│   └── anthropic/     # Anthropic API integration
├── client/            # Client-side examples
│   ├── example_health_check.py
│   ├── example_parse_usage.py
│   ├── example_calculate_payment.py
│   ├── example_settle.py
│   └── example_request.py
└── server/            # Server-side examples
    ├── example.py
    ├── full_flow_example.py
    ├── settlement_service_example.py
    └── client_smoke_test.py
```

## Quick Navigation

### 🎓 [Framework Tutorials](./tutorials/)
Step-by-step tutorials for integrating ATP Protocol with AI agent frameworks:
- [Swarms](./tutorials/swarms/) - Enterprise-grade multi-agent orchestration
- [LangChain](./tutorials/langchain/) - Popular Python LLM framework
- [AutoGen](./tutorials/autogen/) - Microsoft's multi-agent framework
- [CrewAI](./tutorials/crewai/) - Multi-agent orchestration
- [Anthropic](./tutorials/anthropic/) - Claude API integration

### 💻 [Client Examples](./client/)
Simple examples demonstrating the ATP Client API:
- Health check
- Parse usage
- Calculate payment
- Execute settlement
- Make requests to ATP-protected endpoints

### 🖥️ [Server Examples](./server/)
Server-side examples for ATP middleware and settlement:
- Basic middleware setup
- Full payment flow
- Settlement service usage
- Client smoke tests

## Quick Start

### Option 1: Framework Integration (Recommended for Beginners)

1. **Choose a framework tutorial:**
   ```bash
   cd examples/tutorials/swarms  # or langchain, autogen, crewai, anthropic
   ```

2. **Follow the README.md** in that directory for setup instructions

3. **Run the server:**
   ```bash
   python server.py
   ```

4. **Test with the client:**
   ```bash
   python client.py
   ```

### Option 2: Client API Examples

1. **Navigate to client examples:**
   ```bash
   cd examples/client
   ```

2. **Run a simple example:**
   ```bash
   python example_health_check.py
   ```

3. **See [Client README](./client/README.md)** for all examples

### Option 3: Server Examples

1. **Navigate to server examples:**
   ```bash
   cd examples/server
   ```

2. **Run a server example:**
   ```bash
   python example.py
   ```

3. **See [Server README](./server/README.md)** for all examples

## Common Setup

### Environment Variables

Most examples require these environment variables:

```bash
# Required for client examples
ATP_WALLET_PRIVATE_KEY="[1,2,3,...]"  # Your wallet private key

# Required for framework tutorials
OPENAI_API_KEY="your-key"  # For Swarms, LangChain, AutoGen, CrewAI
ANTHROPIC_API_KEY="your-key"  # For Anthropic

# Optional
ATP_SETTLEMENT_URL="https://facilitator.swarms.world"
ATP_RECIPIENT_PUBKEY="YourRecipientPublicKey"
ATP_ENDPOINT_URL="http://localhost:8000/v1/chat"
```

### Server Configuration

Update the `recipient_pubkey` in server examples:

```python
app.add_middleware(
    ATPSettlementMiddleware,
    recipient_pubkey="YourSolanaWalletHere",  # ← Update this!
    # ... other config
)
```

## Payment Details

All examples use the same payment structure:

- **Input tokens**: $10 per million tokens
- **Output tokens**: $30 per million tokens
- **Payment split**: 95% to your wallet, 5% to Swarms Treasury
- **Payment token**: SOL (configurable to USDC)

## What Each Section Contains

### Tutorials (`tutorials/`)

Complete integration guides for popular AI frameworks. Each tutorial includes:
- **Server** (`server.py`) - FastAPI server with ATP middleware
- **Client** (`client.py`) - Example client code
- **README.md** - Framework-specific documentation

**Best for:** Learning how to integrate ATP Protocol with your chosen framework.

### Client Examples (`client/`)

Simple, focused examples demonstrating the ATP Client API:
- Health checking the facilitator
- Parsing usage from various formats
- Calculating payments
- Executing settlements
- Making requests to ATP-protected endpoints

**Best for:** Understanding the client API and testing functionality.

### Server Examples (`server/`)

Server-side examples showing:
- Basic middleware setup
- Complete payment flows
- Settlement service integration
- Testing and validation

**Best for:** Understanding server-side implementation and payment flows.

## Troubleshooting

### Common Issues

1. **Missing wallet key**: Ensure `ATP_WALLET_PRIVATE_KEY` is set
2. **Invalid recipient pubkey**: Update `recipient_pubkey` in server files
3. **API key errors**: Verify your framework's API key is set correctly
4. **Payment failures**: Check Solana wallet has sufficient balance

### Getting Help

- Check the specific README in each example directory
- Review the main [ATP Protocol README](../README.md)
- Verify environment variables are set correctly

## Next Steps

After running examples:

1. **Customize** agent configuration for your use case
2. **Implement** proper token tracking (use actual API responses when available)
3. **Add** authentication/authorization layers
4. **Configure** custom pricing rates
5. **Deploy** to production

## Resources

- [ATP Protocol Documentation](../README.md)
- [Client API Documentation](../atp/client.py)
- [Middleware Documentation](../atp/middleware.py)
- [Swarms Framework](https://github.com/kyegomez/swarms)
- [LangChain Documentation](https://python.langchain.com/)
- [AutoGen Documentation](https://microsoft.github.io/autogen/)
- [CrewAI Documentation](https://docs.crewai.com/)
- [Anthropic API Documentation](https://docs.anthropic.com/)
