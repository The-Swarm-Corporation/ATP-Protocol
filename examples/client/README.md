# ATP Client Examples

Simple examples demonstrating how to use the ATP Client API to interact with the facilitator (settlement service) and ATP-protected endpoints.

## Examples

### `example_health_check.py`

Check if the facilitator (settlement service) is healthy and running.

```bash
python examples/client/example_health_check.py
```

**What it does:**
- Initializes the ATP client
- Calls the health check endpoint
- Prints the health status

**No environment variables required.**

---

### `example_parse_usage.py`

Parse usage tokens from different API formats (OpenAI, Anthropic, etc.) into a normalized format.

```bash
python examples/client/example_parse_usage.py
```

**What it does:**
- Initializes the ATP client
- Parses usage data from OpenAI format
- Prints the normalized usage (input_tokens, output_tokens, total_tokens)

**No environment variables required.**

---

### `example_calculate_payment.py`

Calculate payment amounts from usage data without executing a payment.

```bash
python examples/client/example_calculate_payment.py
```

**What it does:**
- Initializes the ATP client
- Calculates payment for 1000 input tokens and 500 output tokens
- Uses $10/M input and $30/M output pricing
- Prints payment calculation details

**No environment variables required.**

---

### `example_settle.py`

Execute a settlement payment on Solana blockchain.

```bash
export ATP_WALLET_PRIVATE_KEY="[1,2,3,...]"
export ATP_RECIPIENT_PUBKEY="RecipientPublicKeyHere"
python examples/client/example_settle.py
```

**What it does:**
- Initializes the ATP client with wallet
- Executes a settlement for 1000 input tokens and 500 output tokens
- Sends payment transaction on Solana
- Prints settlement result with transaction signature

**Environment variables:**
- `ATP_WALLET_PRIVATE_KEY` (required) - Your wallet private key
- `ATP_RECIPIENT_PUBKEY` (optional) - Recipient public key (defaults to placeholder)

**⚠️ WARNING:** This will execute a REAL payment transaction on Solana!

---

### `example_request.py`

Make a request to an ATP-protected endpoint with automatic wallet authentication and response decryption.

```bash
export ATP_WALLET_PRIVATE_KEY="[1,2,3,...]"
export ATP_ENDPOINT_URL="http://localhost:8000/v1/chat"
python examples/client/example_request.py
```

**What it does:**
- Initializes the ATP client with wallet
- Makes a POST request to an ATP-protected endpoint
- Automatically includes wallet authentication headers
- Automatically decrypts encrypted responses
- Prints the response

**Environment variables:**
- `ATP_WALLET_PRIVATE_KEY` (required) - Your wallet private key
- `ATP_ENDPOINT_URL` (optional) - Endpoint URL (defaults to `http://localhost:8000/v1/chat`)

---

## Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `ATP_WALLET_PRIVATE_KEY` | Wallet private key for authentication and payments | For settle/request examples | None |
| `ATP_RECIPIENT_PUBKEY` | Recipient public key for settlement | For settle example | `RecipientPublicKeyHere` |
| `ATP_ENDPOINT_URL` | URL of ATP-protected endpoint | For request example | `http://localhost:8000/v1/chat` |
| `ATP_SETTLEMENT_URL` | Settlement service (facilitator) URL | No | `https://facilitator.swarms.world` |
| `ATP_SETTLEMENT_TIMEOUT` | Timeout for settlement operations (seconds) | No | `300.0` |

## Quick Start

1. **Install the package:**
   ```bash
   pip install atp-protocol
   ```

2. **Run a simple example (no setup required):**
   ```bash
   python examples/client/example_health_check.py
   ```

3. **Run examples that require wallet:**
   ```bash
   export ATP_WALLET_PRIVATE_KEY="[1,2,3,...]"
   python examples/client/example_settle.py
   ```

## Features Demonstrated

- ✅ Health checking the facilitator
- ✅ Parsing usage from various API formats
- ✅ Calculating payment amounts
- ✅ Executing settlements on Solana
- ✅ Making requests to ATP-protected endpoints
- ✅ Automatic wallet authentication
- ✅ Automatic response decryption

## See Also

- [ATP Client API Documentation](../../atp/client.py) - Full client API reference
- [Main README](../../README.md) - Complete ATP Protocol documentation
- [Other Examples](../README.md) - Server-side middleware examples
