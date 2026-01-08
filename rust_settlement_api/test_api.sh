#!/bin/bash

# ATP Settlement Service API Test Examples
# Make sure the service is running on http://localhost:8001

BASE_URL="http://localhost:8001"

echo "=== Testing ATP Settlement Service API ==="
echo ""

# 1. Health Check
echo "1. Health Check"
echo "GET $BASE_URL/health"
curl -X GET "$BASE_URL/health" \
  -H "Content-Type: application/json" \
  -w "\n\n"
echo ""

# 2. Parse Usage Tokens - OpenAI Format
echo "2. Parse Usage Tokens (OpenAI Format)"
echo "POST $BASE_URL/v1/settlement/parse-usage"
curl -X POST "$BASE_URL/v1/settlement/parse-usage" \
  -H "Content-Type: application/json" \
  -d '{
    "usage_data": {
      "prompt_tokens": 100,
      "completion_tokens": 50,
      "total_tokens": 150
    }
  }' \
  -w "\n\n"
echo ""

# 3. Parse Usage Tokens - Anthropic Format
echo "3. Parse Usage Tokens (Anthropic Format)"
curl -X POST "$BASE_URL/v1/settlement/parse-usage" \
  -H "Content-Type: application/json" \
  -d '{
    "usage_data": {
      "input_tokens": 200,
      "output_tokens": 100,
      "total_tokens": 300
    }
  }' \
  -w "\n\n"
echo ""

# 4. Parse Usage Tokens - Google/Gemini Format
echo "4. Parse Usage Tokens (Google/Gemini Format)"
curl -X POST "$BASE_URL/v1/settlement/parse-usage" \
  -H "Content-Type: application/json" \
  -d '{
    "usage_data": {
      "promptTokenCount": 150,
      "candidatesTokenCount": 75,
      "totalTokenCount": 225
    }
  }' \
  -w "\n\n"
echo ""

# 5. Calculate Payment
echo "5. Calculate Payment"
echo "POST $BASE_URL/v1/settlement/calculate-payment"
curl -X POST "$BASE_URL/v1/settlement/calculate-payment" \
  -H "Content-Type: application/json" \
  -d '{
    "usage": {
      "input_tokens": 1000,
      "output_tokens": 500,
      "total_tokens": 1500
    },
    "input_cost_per_million_usd": 2.50,
    "output_cost_per_million_usd": 10.00,
    "payment_token": "SOL"
  }' \
  -w "\n\n"
echo ""

# 6. Calculate Payment - USDC
echo "6. Calculate Payment (USDC)"
curl -X POST "$BASE_URL/v1/settlement/calculate-payment" \
  -H "Content-Type: application/json" \
  -d '{
    "usage": {
      "input_tokens": 2000,
      "output_tokens": 1000,
      "total_tokens": 3000
    },
    "input_cost_per_million_usd": 5.00,
    "output_cost_per_million_usd": 15.00,
    "payment_token": "USDC"
  }' \
  -w "\n\n"
echo ""

# 7. Settle Payment (WARNING: This requires a real private key - use testnet/devnet for testing!)
echo "7. Settle Payment (Example - DO NOT USE REAL PRIVATE KEYS IN PRODUCTION)"
echo "POST $BASE_URL/v1/settlement/settle"
echo "NOTE: Replace PRIVATE_KEY and RECIPIENT_PUBKEY with test values"
echo ""
echo "Example request body:"
cat << 'EOF'
{
  "private_key": "[1,2,3,...64 bytes...]",
  "usage": {
    "input_tokens": 1000,
    "output_tokens": 500,
    "total_tokens": 1500
  },
  "input_cost_per_million_usd": 2.50,
  "output_cost_per_million_usd": 10.00,
  "recipient_pubkey": "RecipientWalletAddressHere",
  "payment_token": "SOL",
  "treasury_pubkey": null,
  "skip_preflight": false,
  "commitment": "confirmed"
}
EOF
echo ""

echo "=== Test Complete ==="

