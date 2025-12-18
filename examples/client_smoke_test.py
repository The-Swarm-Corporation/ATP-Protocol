"""
ATP Protocol - Client Smoke Test (simple)
========================================

This is a *client-facing* smoke test file that exercises the ATP Gateway API using httpx.

It performs:
- GET /health
- (best-effort) GET /v1/token/price/{token}
- (best-effort) GET /v1/payment/info
- POST /v1/agent/trade (expects HTTP 402 Payment Required)
- POST /v1/agent/settle (facilitator signs+submits payment using provided private key)

No CLI parsing and no printing; on failures it raises exceptions.

Configure via environment variables:
- ATP_BASE_URL (default: http://localhost:8000)
- ATP_USER_WALLET (required)
- ATP_PAYMENT_TOKEN (default: SOL)  # SOL or USDC
- ATP_TASK (optional)
- ATP_PRIVATE_KEY (required; payer private key string used for signed settlement)
- ATP_JOB_ID (optional; if not set, uses job_id returned by /v1/agent/trade)
- ATP_OUTPUT_PATH (default: examples/client_smoke_test_output.json)
"""

from __future__ import annotations

import json
import os

import httpx


if __name__ == "__main__":
    base_url = os.getenv("ATP_BASE_URL", "http://localhost:8000").rstrip("/")
    user_wallet = os.getenv("ATP_USER_WALLET")
    token = os.getenv("ATP_PAYMENT_TOKEN", "SOL").upper()
    task = os.getenv(
        "ATP_TASK",
        "Say 'hello from ATP client smoke test' and return a short JSON object.",
    )
    private_key = os.getenv("ATP_PRIVATE_KEY")
    job_id = os.getenv("ATP_JOB_ID")
    output_path = os.getenv("ATP_OUTPUT_PATH", "examples/client_smoke_test_output.json")

    if not user_wallet:
        raise RuntimeError("ATP_USER_WALLET is required")
    if not private_key:
        raise RuntimeError("ATP_PRIVATE_KEY is required")
    if token not in {"SOL", "USDC"}:
        raise RuntimeError("ATP_PAYMENT_TOKEN must be SOL or USDC")

    results = {}

    with httpx.Client(base_url=base_url, timeout=120.0) as client:
        # 1) Health (required)
        health = client.get("/health")
        health.raise_for_status()
        results["health"] = health.json()

        # 2) Token price + payment info (best-effort)
        try:
            price = client.get(f"/v1/token/price/{token}")
            price.raise_for_status()
            results["token_price"] = price.json()
        except Exception:
            pass

        try:
            info = client.get("/v1/payment/info")
            info.raise_for_status()
            results["payment_info"] = info.json()
        except Exception:
            pass

        # 3) Trade: expects 402 Payment Required
        payload = {
            "agent_config": {
                "agent_name": "atp-client-smoke-test",
                "description": "Smoke test agent invocation via ATP Gateway",
                "model_name": "gpt-4.1",
                "max_loops": 1,
                "temperature": 0.2,
            },
            "task": task,
            "user_wallet": user_wallet,
            "payment_token": token,
        }
        trade = client.post("/v1/agent/trade", json=payload)
        if trade.status_code != 402:
            raise RuntimeError(
                f"Expected HTTP 402 from /v1/agent/trade, got {trade.status_code}: {trade.text}"
            )
        results["trade_402"] = trade.json()

        # 4) Settlement (required): facilitator signs+sends payment, then releases output
        resolved_job_id = job_id or results["trade_402"].get("job_id")
        if not resolved_job_id:
            raise RuntimeError(
                "ATP_JOB_ID not provided and no job_id returned by /v1/agent/trade"
            )

        settle_payload = {"job_id": resolved_job_id, "private_key": private_key}
        settle = client.post("/v1/agent/settle", json=settle_payload)
        settle.raise_for_status()
        results["settlement_200"] = settle.json()

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, sort_keys=False)
