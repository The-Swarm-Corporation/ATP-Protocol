# Server Examples

This directory contains server-side examples demonstrating ATP Protocol middleware and settlement service usage.

## Examples

### `example.py`

Basic example showing how to add ATP settlement middleware to any FastAPI endpoint.

**Features:**
- Simple FastAPI server with ATP middleware
- Multiple endpoints with different usage formats
- Automatic payment processing

**Run:**
```bash
python examples/server/example.py
```

---

### `full_flow_example.py`

Complete end-to-end flow example demonstrating the trade → settle payment pattern.

**Features:**
- POST `/v1/agent/trade` - Creates a trade and returns payment challenge (HTTP 402)
- POST `/v1/agent/settle` - Executes settlement and unlocks output
- Complete payment flow demonstration

**Run:**
```bash
export ATP_BASE_URL="http://localhost:8000"
export ATP_USER_WALLET="YourPublicKey"
export ATP_PRIVATE_KEY="[1,2,3,...]"
python examples/server/full_flow_example.py
```

**⚠️ WARNING:** This can broadcast real SOL transactions when settlement is enabled.

---

### `settlement_service_example.py`

Example demonstrating how to use the ATP Settlement Service directly.

**Features:**
- Standalone settlement service usage
- Direct HTTP calls to settlement service
- Middleware integration with settlement service

**Run:**
```bash
python examples/server/settlement_service_example.py
```

---

### `client_smoke_test.py`

Client-facing smoke test that exercises the ATP Gateway API.

**Features:**
- Health check endpoint
- Token price endpoint
- Payment info endpoint
- Trade endpoint (expects HTTP 402)
- Settle endpoint

**Run:**
```bash
export ATP_BASE_URL="http://localhost:8000"
export ATP_USER_WALLET="YourPublicKey"
export ATP_PRIVATE_KEY="[1,2,3,...]"
python examples/server/client_smoke_test.py
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `ATP_BASE_URL` | Base URL of the ATP Gateway | For full_flow_example, client_smoke_test |
| `ATP_USER_WALLET` | Payer public key | For full_flow_example, client_smoke_test |
| `ATP_PRIVATE_KEY` | Payer private key | For full_flow_example, client_smoke_test |
| `ATP_ALLOW_SPEND` | Enable settlement (spends SOL) | For full_flow_example |
| `ATP_PAYMENT_TOKEN` | Payment token (SOL or USDC) | For client_smoke_test |
| `ATP_TASK` | Task to execute | For client_smoke_test (optional) |
| `ATP_JOB_ID` | Job ID for settlement | For client_smoke_test (optional) |

## See Also

- [Client Examples](../client/README.md) - Client-side examples
- [Framework Tutorials](../tutorials/README.md) - Framework integration tutorials
- [Main Examples README](../README.md) - Complete examples documentation
