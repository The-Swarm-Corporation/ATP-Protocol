# Anthropic API + ATP Protocol Integration

This example demonstrates how to integrate **ATP Protocol** with **Anthropic's Claude API** to enable automatic payment processing for Anthropic-based AI services.

## Overview

This integration allows you to:
- Use Anthropic's Claude API with automatic Solana payment processing
- Charge users based on actual token usage (input/output tokens from Anthropic)
- Receive payments directly to your Solana wallet
- Use ATP middleware to handle all payment logic automatically
- Support both OpenAI-compatible and native Anthropic API formats

## Installation

```bash
# Install required packages
pip install anthropic atp-protocol fastapi uvicorn httpx python-dotenv

# Or install from requirements
pip install -r requirements.txt
```

## Environment Setup

Create a `.env` file in this directory:

```bash
# Required: Anthropic API key
ANTHROPIC_API_KEY="your-anthropic-api-key"

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
    allowed_endpoints=["/v1/chat/completions", "/v1/messages"],
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

### 1. Chat Completions (OpenAI-Compatible)

**POST** `/v1/chat/completions`

Chat completions endpoint compatible with OpenAI's format.

**Request:**
```json
{
    "model": "claude-3-5-sonnet-20241022",
    "messages": [
        {"role": "user", "content": "What are the key benefits of using AI agents?"}
    ],
    "max_tokens": 1024
}
```

**Response:**
```json
{
    "id": "msg_01XFDUDYJgAACzvnptvVoYEL",
    "model": "claude-3-5-sonnet-20241022",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "AI agents offer several key benefits..."
            },
            "finish_reason": "end_turn"
        }
    ],
    "usage": {
        "input_tokens": 15,
        "output_tokens": 150,
        "total_tokens": 165
    },
    "atp_settlement": {
        "status": "paid",
        "transaction_signature": "5j7s8K9...",
        "payment": {
            "total_amount_sol": 0.00495,
            "recipient": {"amount_sol": 0.0047025},
            "treasury": {"amount_sol": 0.0002475}
        }
    }
}
```

### 2. Messages API (Native Anthropic Format)

**POST** `/v1/messages`

Anthropic's native Messages API format.

**Request:**
```json
{
    "model": "claude-3-5-sonnet-20241022",
    "messages": [
        {"role": "user", "content": "Explain the concept of agentic AI in simple terms."}
    ],
    "max_tokens": 1024,
    "system": "You are a helpful AI assistant that explains complex concepts clearly."
}
```

**Response:**
```json
{
    "id": "msg_01XFDUDYJgAACzvnptvVoYEL",
    "type": "message",
    "role": "assistant",
    "content": [
        {
            "type": "text",
            "text": "Agentic AI refers to AI systems that can act autonomously..."
        }
    ],
    "model": "claude-3-5-sonnet-20241022",
    "stop_reason": "end_turn",
    "stop_sequence": null,
    "usage": {
        "input_tokens": 25,
        "output_tokens": 200,
        "total_tokens": 225
    },
    "atp_settlement": {
        "status": "paid",
        "transaction_signature": "5j7s8K9...",
        "payment": {
            "total_amount_sol": 0.00675,
            "recipient": {"amount_sol": 0.0064125},
            "treasury": {"amount_sol": 0.0003375}
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
    "api_ready": true,
    "atp_middleware": "active",
    "provider": "anthropic"
}
```

## How It Works

1. **Client sends request** with wallet private key in `x-wallet-private-key` header
2. **ATP middleware intercepts** the request and forwards it to your endpoint
3. **Anthropic API is called** with the request parameters
4. **Usage data is extracted** from Anthropic's response (actual token counts)
5. **ATP middleware calculates** payment based on token usage
6. **Payment is processed** on Solana (95% to you, 5% to Swarms Treasury)
7. **Response includes** settlement details with transaction signature

## Payment Details

- **Input tokens**: $10 per million tokens
- **Output tokens**: $30 per million tokens
- **Payment split**: 95% to your wallet, 5% to Swarms Treasury
- **Payment token**: SOL (configurable to USDC)

## Usage Tracking

This example uses **actual token usage** from Anthropic's API response, which provides accurate token counts:

```python
usage = {
    "input_tokens": response.usage.input_tokens,
    "output_tokens": response.usage.output_tokens,
    "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
}
```

The ATP middleware automatically detects this format and uses it for payment calculation.

## Supported Models

- `claude-3-5-sonnet-20241022` (default)
- `claude-3-opus-20240229`
- `claude-3-sonnet-20240229`
- `claude-3-haiku-20240307`
- `claude-3-5-haiku-20241022`

## Multi-Turn Conversations

The API supports multi-turn conversations by maintaining message history:

```python
messages = [
    {"role": "user", "content": "What is machine learning?"},
    {"role": "assistant", "content": "Machine learning is..."},
    {"role": "user", "content": "Can you give me a practical example?"}
]
```

## Error Handling

- **Missing wallet key**: Returns `401 Unauthorized`
- **Missing usage data**: Logs warning and returns original response
- **Payment failure**: Returns `500 Internal Server Error` with details
- **Invalid private key**: Returns `500 Internal Server Error` with parsing error
- **Anthropic API errors**: Returns `500 Internal Server Error` with API error details

## Security Considerations

- Private keys are only used in-memory during each request
- Keys are never persisted or logged
- All settlement logic is handled by the ATP Settlement Service
- Transactions are verified before responses are returned
- Anthropic API keys are stored securely in environment variables

## Next Steps

- Add streaming support for real-time responses
- Implement rate limiting and usage quotas
- Add support for vision models (image inputs)
- Configure custom pricing rates per model
- Add authentication/authorization layers
- Implement conversation history management
- Add support for tool use and function calling

## Resources

- [Anthropic API Documentation](https://docs.anthropic.com/)
- [ATP Protocol Documentation](../README.md)
- [Swarms Framework](https://github.com/kyegomez/swarms)

