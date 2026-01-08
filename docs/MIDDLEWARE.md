# ATP Settlement Middleware

A flexible FastAPI middleware that enables automatic payment deduction from Solana wallets based on token usage for any endpoint.

## Features

- **Automatic Payment Deduction**: Automatically deducts payment from Solana wallets based on token usage
- **Configurable Pricing**: Set custom costs per million input/output tokens per endpoint
- **Flexible Endpoint Selection**: Choose which endpoints should have settlement enabled
- **Simple Wallet Integration**: Accepts wallet private keys directly via headers - no API key management required
- **Usage Tracking**: Extracts usage data from responses and includes it in the response
- **Multiple Token Support**: Supports SOL and USDC (SOL only for automatic settlement currently)
- **Extensible**: Easy to add your own API key handling layer if needed

## Quick Start

### 1. Basic Usage

```python
from fastapi import FastAPI
from atp.middleware import ATPSettlementMiddleware
from atp.schemas import PaymentToken

app = FastAPI()

# Add the middleware
app.add_middleware(
    ATPSettlementMiddleware,
    allowed_endpoints=["/v1/chat", "/v1/completions"],
    input_cost_per_million_usd=10.0,
    output_cost_per_million_usd=30.0,
)
```

Clients simply include their wallet private key in the `x-wallet-private-key` header:

```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "x-wallet-private-key: [1,2,3,...]" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello"}'
```

### 2. Endpoint with Usage Data

Your endpoints should return usage data in the response:

```python
@app.post("/v1/chat")
async def chat_endpoint(request: dict):
    return {
        "output": "Response text",
        "usage": {
            "input_tokens": 150,
            "output_tokens": 50,
            "total_tokens": 200,
        },
    }
```

The middleware will:
1. Extract usage from the response
2. Calculate cost based on configured rates
3. Deduct payment from the wallet provided in the header
4. Add settlement information to the response

### 3. Response Format

After settlement, responses include additional fields:

```json
{
    "output": "Response text",
    "usage": {
        "input_tokens": 150,
        "output_tokens": 50,
        "total_tokens": 200
    },
    "atp_settlement": {
        "status": "paid",
        "transaction_signature": "5j7s8K9...",
        "pricing": {
            "usd_cost": 0.0025,
            "input_cost_usd": 0.0015,
            "output_cost_usd": 0.0010,
            "source": "middleware_rates"
        },
        "payment": {
            "amount_lamports": 25000,
            "amount_sol": 0.000025,
            "amount_usd": 0.0025,
            "recipient": "7MaX4muAn8ZQREJxnupm8sgokwFHujgrGfH9Qn81BuEV"
        }
    },
    "atp_usage": {
        "input_tokens": 150,
        "output_tokens": 50,
        "total_tokens": 200
    }
}
```

## Configuration Options

**Important**: The treasury pubkey is immutable and always uses `config.SWARMS_TREASURY_PUBKEY` to ensure Swarms receives the processing fee. It cannot be overridden via middleware parameters.

### Middleware Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `allowed_endpoints` | `List[str]` | **Required** | List of endpoint paths to apply settlement to |
| `input_cost_per_million_usd` | `float` | **Required** | Cost per million input tokens in USD |
| `output_cost_per_million_usd` | `float` | **Required** | Cost per million output tokens in USD |
| `wallet_private_key_header` | `str` | `"x-wallet-private-key"` | HTTP header name containing the wallet private key |
| `payment_token` | `PaymentToken` | `PaymentToken.SOL` | Token to use for payment (SOL or USDC) |
| `skip_preflight` | `bool` | `False` | Skip preflight simulation for Solana transactions |
| `commitment` | `str` | `"confirmed"` | Solana commitment level (processed\|confirmed\|finalized) |
| `usage_response_key` | `str` | `"usage"` | Key in response JSON where usage data is located |
| `include_usage_in_response` | `bool` | `True` | Whether to add usage/cost info to the response |
| `require_wallet` | `bool` | `True` | Whether to require wallet private key (if False, skips settlement) |

### Example: Full Configuration

```python
app.add_middleware(
    ATPSettlementMiddleware,
    allowed_endpoints=[
        "/v1/chat",
        "/v1/completions",
        "/v1/agent/execute",
    ],
    input_cost_per_million_usd=10.0,
    output_cost_per_million_usd=30.0,
    wallet_private_key_header="x-wallet-private-key",
    payment_token=PaymentToken.SOL,
    # Note: treasury_pubkey is immutable and always uses config.SWARMS_TREASURY_PUBKEY
    skip_preflight=False,
    commitment="confirmed",
    usage_response_key="usage",
    include_usage_in_response=True,
    require_wallet=True,
)
```

## Wallet Private Key Format

The middleware accepts Solana wallet private keys in two formats:

1. **JSON Array Format** (recommended):
   ```
   [1,2,3,4,5,...]
   ```

2. **Base58 String Format** (if supported by your Solana library):
   ```
   base58encodedstring...
   ```

The private key is passed via the `x-wallet-private-key` header (or your custom header name).

## Adding Your Own API Key Layer

If you want to add API key handling, you can create a custom dependency or middleware:

```python
from fastapi import Depends, Header, HTTPException
from typing import Dict

# Your API key to wallet mapping (use a database in production)
API_KEY_TO_WALLET: Dict[str, str] = {
    "user_api_key_123": "[1,2,3,...]",  # Solana private key
}

def get_wallet_from_api_key(api_key: str = Header(..., alias="x-api-key")) -> str:
    """Custom dependency to map API keys to wallet private keys."""
    if api_key not in API_KEY_TO_WALLET:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return API_KEY_TO_WALLET[api_key]

# Then use a custom middleware to inject the wallet private key header
# before the ATP middleware processes the request
```

## Usage Data Formats

The middleware supports multiple usage data formats:

### Format 1: Standard (Recommended)
```json
{
    "usage": {
        "input_tokens": 150,
        "output_tokens": 50,
        "total_tokens": 200
    }
}
```

### Format 2: OpenAI-style
```json
{
    "usage": {
        "prompt_tokens": 150,
        "completion_tokens": 50,
        "total_tokens": 200
    }
}
```

### Format 3: Direct in Response
If the entire response is usage-like, it will be detected automatically.

## Error Handling

The middleware handles various error scenarios:

- **Missing API Key**: Returns 401 if API key is required but not provided
- **Invalid API Key**: Returns 401 if API key is not registered
- **No Usage Data**: Skips settlement if usage data is not found in response
- **Payment Failure**: Returns 500 if payment deduction fails
- **Invalid Private Key**: Returns 500 if wallet private key is invalid

## Advanced Usage

### Custom Usage Extraction

You can customize how usage is extracted by setting `usage_response_key`:

```python
app.add_middleware(
    ATPSettlementMiddleware,
    allowed_endpoints=["/v1/custom"],
    input_cost_per_million_usd=10.0,
    output_cost_per_million_usd=30.0,
    usage_response_key="token_usage",  # Custom key name
)
```

### Optional Wallet

If you want to allow endpoints to work without wallet private keys (but still settle when provided):

```python
app.add_middleware(
    ATPSettlementMiddleware,
    allowed_endpoints=["/v1/chat"],
    input_cost_per_million_usd=10.0,
    output_cost_per_million_usd=30.0,
    require_wallet=False,  # Allow requests without wallet private key
)
```

### Multiple Middleware Instances

You can add multiple middleware instances with different configurations:

```python
# Middleware for chat endpoints
app.add_middleware(
    ATPSettlementMiddleware,
    allowed_endpoints=["/v1/chat"],
    input_cost_per_million_usd=10.0,
    output_cost_per_million_usd=30.0,
)

# Middleware for expensive endpoints
app.add_middleware(
    ATPSettlementMiddleware,
    allowed_endpoints=["/v1/expensive-operation"],
    input_cost_per_million_usd=50.0,
    output_cost_per_million_usd=100.0,
)
```

## Production Considerations

1. **Security**: 
   - Use HTTPS to protect wallet private keys in transit
   - Consider using environment variables or secure vaults for treasury keys
   - Implement rate limiting on settlement endpoints
   - Add request signing/authentication if needed

2. **Error Handling**: 
   - Implement retry logic for failed payments
   - Log all settlement attempts for auditing (without logging private keys)
   - Consider idempotency keys for payment requests

3. **Monitoring**: 
   - Track settlement success/failure rates
   - Monitor wallet balances
   - Alert on payment failures

4. **API Key Layer**: If you need API key handling, implement it as a separate layer:
   - Create a custom middleware that maps API keys to wallet private keys
   - Use a database or key management service to store the mapping
   - Inject the wallet private key header before the ATP middleware processes the request

## Example: Complete Integration

See `examples/middleware_usage_example.py` for a complete working example.

## Troubleshooting

### Payment Not Deducted

- Check that the endpoint is in `allowed_endpoints`
- Verify usage data is in the response with the correct key
- Ensure wallet private key is provided in the header
- Check wallet has sufficient balance

### Usage Not Detected

- Verify response includes usage data
- Check `usage_response_key` matches your response structure
- Ensure response is valid JSON

### Transaction Failures

- Check Solana RPC endpoint is accessible
- Verify wallet has sufficient balance
- Check transaction commitment level
- Review Solana network status

