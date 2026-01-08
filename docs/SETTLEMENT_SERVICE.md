# ATP Settlement Service

The ATP Settlement Service is a standalone FastAPI server that provides immutable settlement logic for the ATP Protocol. This service centralizes all settlement operations, making the logic immutable and easier to maintain.

## Overview

The settlement service handles:
- **Usage Token Parsing**: Parses usage tokens from various API formats (OpenAI, Anthropic, Google/Gemini, Cohere, etc.)
- **Payment Calculation**: Calculates payment amounts from usage data based on configured rates
- **Settlement Execution**: Executes Solana payments with automatic fee splitting (treasury + recipient)

## Architecture

The settlement service is designed to be:
- **Immutable**: All configuration comes from environment variables or request parameters. No mutable state in the settlement logic.
- **Stateless**: Each request is independent and doesn't rely on previous requests.
- **Centralized**: Single source of truth for settlement logic across all ATP Protocol deployments.

## Running the Service

### Standalone Server

Run the settlement service as a standalone FastAPI server:

```bash
# Using uvicorn directly
uvicorn atp.settlement_service:settlement_app --host 0.0.0.0 --port 8001

# Or using Python
python -m atp.settlement_service
```

### Docker

You can containerize the settlement service:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY atp/ ./atp/
COPY .env .env  # Your environment variables

CMD ["uvicorn", "atp.settlement_service:settlement_app", "--host", "0.0.0.0", "--port", "8001"]
```

## API Endpoints

### Health Check

```http
GET /health
```

Returns the health status of the service.

**Response:**
```json
{
  "status": "healthy",
  "service": "ATP Settlement Service",
  "version": "1.0.0"
}
```

### Parse Usage Tokens

```http
POST /v1/settlement/parse-usage
```

Parses usage tokens from various API formats.

**Request Body:**
```json
{
  "usage_data": {
    "prompt_tokens": 100,
    "completion_tokens": 50,
    "total_tokens": 150
  }
}
```

**Response:**
```json
{
  "input_tokens": 100,
  "output_tokens": 50,
  "total_tokens": 150
}
```

**Supported Formats:**
- OpenAI: `prompt_tokens`, `completion_tokens`, `total_tokens`
- Anthropic: `input_tokens`, `output_tokens`, `total_tokens`
- Google/Gemini: `promptTokenCount`, `candidatesTokenCount`, `totalTokenCount`
- Cohere: `tokens`, `input_tokens`, `output_tokens`
- Generic: `input_tokens`, `output_tokens`, `total_tokens`

### Calculate Payment

```http
POST /v1/settlement/calculate-payment
```

Calculates payment amounts from usage data.

**Request Body:**
```json
{
  "usage": {
    "input_tokens": 100,
    "output_tokens": 50,
    "total_tokens": 150
  },
  "input_cost_per_million_usd": 10.0,
  "output_cost_per_million_usd": 30.0,
  "payment_token": "SOL"
}
```

**Response:**
```json
{
  "status": "calculated",
  "pricing": {
    "usd_cost": 0.0025,
    "source": "settlement_service_rates",
    "input_tokens": 100,
    "output_tokens": 50,
    "total_tokens": 150,
    "input_cost_per_million_usd": 10.0,
    "output_cost_per_million_usd": 30.0,
    "input_cost_usd": 0.001,
    "output_cost_usd": 0.0015
  },
  "payment_amounts": {
    "total_amount_units": 2500,
    "agent_amount_units": 2375,
    "fee_amount_units": 125,
    "total_amount_token": 0.000025,
    "agent_amount_token": 0.00002375,
    "fee_amount_token": 0.00000125,
    "decimals": 9,
    "fee_percent": 5.0
  },
  "token_price_usd": 100.0
}
```

### Execute Settlement

```http
POST /v1/settlement/settle
```

Executes a settlement payment on Solana.

**Request Body:**
```json
{
  "private_key": "[1,2,3,...]",
  "usage": {
    "input_tokens": 100,
    "output_tokens": 50,
    "total_tokens": 150
  },
  "input_cost_per_million_usd": 10.0,
  "output_cost_per_million_usd": 30.0,
  "recipient_pubkey": "YourRecipientPubkeyHere",
  "payment_token": "SOL",
  "treasury_pubkey": "7MaX4muAn8ZQREJxnupm8sgokwFHujgrGfH9Qn81BuEV",
  "skip_preflight": false,
  "commitment": "confirmed"
}
```

**Response:**
```json
{
  "status": "paid",
  "transaction_signature": "5j7s8K9m...",
  "pricing": {
    "usd_cost": 0.0025,
    "source": "settlement_service_rates",
    "input_tokens": 100,
    "output_tokens": 50,
    "total_tokens": 150,
    "input_cost_per_million_usd": 10.0,
    "output_cost_per_million_usd": 30.0,
    "input_cost_usd": 0.001,
    "output_cost_usd": 0.0015
  },
  "payment": {
    "total_amount_lamports": 2500,
    "total_amount_sol": 0.000025,
    "total_amount_usd": 0.0025,
    "treasury": {
      "pubkey": "7MaX4muAn8ZQREJxnupm8sgokwFHujgrGfH9Qn81BuEV",
      "amount_lamports": 125,
      "amount_sol": 0.00000125,
      "amount_usd": 0.000125
    },
    "recipient": {
      "pubkey": "YourRecipientPubkeyHere",
      "amount_lamports": 2375,
      "amount_sol": 0.00002375,
      "amount_usd": 0.002375
    }
  }
}
```

## Using with Middleware

The ATP middleware can be configured to use the settlement service instead of executing settlement locally:

```python
from fastapi import FastAPI
from atp.middleware import ATPSettlementMiddleware
from atp.schemas import PaymentToken

app = FastAPI()

app.add_middleware(
    ATPSettlementMiddleware,
    allowed_endpoints=["/v1/chat", "/v1/completions"],
    input_cost_per_million_usd=10.0,
    output_cost_per_million_usd=30.0,
    wallet_private_key_header="x-wallet-private-key",
    payment_token=PaymentToken.SOL,
    recipient_pubkey="YourRecipientPubkeyHere",
    # settlement_service_url is optional - uses ATP_SETTLEMENT_URL env var by default
)
```

## Using the Client Library

You can also use the settlement service client library directly:

```python
from atp.settlement_client import SettlementServiceClient

client = SettlementServiceClient(base_url="http://localhost:8001")

# Parse usage
parsed = await client.parse_usage(usage_data)

# Calculate payment
payment_calc = await client.calculate_payment(
    usage=usage_data,
    input_cost_per_million_usd=10.0,
    output_cost_per_million_usd=30.0,
    payment_token="SOL",
)

# Execute settlement
settlement_result = await client.settle(
    private_key=private_key,
    usage=usage_data,
    input_cost_per_million_usd=10.0,
    output_cost_per_million_usd=30.0,
    recipient_pubkey=recipient_pubkey,
    payment_token="SOL",
)
```

## Environment Variables

The settlement service uses the same environment variables as the main ATP Gateway:

- `SOLANA_RPC_URL`: Solana RPC endpoint (default: `https://api.mainnet-beta.solana.com`)
- `SWARMS_TREASURY_PUBKEY`: Treasury pubkey for processing fees
- `SETTLEMENT_FEE_PERCENT`: Settlement fee percentage (default: `0.05` for 5%)
- `USDC_MINT_ADDRESS`: USDC mint address (for USDC payments)
- `USDC_DECIMALS`: USDC decimals (default: `6`)
- `ATP_SETTLEMENT_URL`: Base URL of the settlement service (default: `http://localhost:8001`)
  - Used by the middleware to connect to the settlement service
  - Can be overridden by passing `settlement_service_url` parameter to the middleware

## Benefits of Using the Settlement Service

1. **Immutability**: Settlement logic is centralized and cannot be modified at runtime
2. **Consistency**: All deployments use the same settlement logic
3. **Maintainability**: Single codebase for settlement operations
4. **Scalability**: Settlement service can be scaled independently
5. **Security**: Private keys are only used in-memory during settlement execution
6. **Testing**: Easier to test settlement logic in isolation

## Security Considerations

- **Private Keys**: Private keys are only used in-memory during settlement execution and are never persisted
- **Network Security**: Use HTTPS in production and secure the settlement service endpoint
- **Authentication**: Consider adding authentication/authorization for production deployments
- **Rate Limiting**: Implement rate limiting to prevent abuse

## Example Usage

See `examples/settlement_service_example.py` for complete examples of:
- Running the settlement service standalone
- Using middleware with settlement service
- Calling the settlement service directly
- Making raw HTTP requests to the service

