"""
ATP Protocol - Full Flow Example (trade -> 402 challenge -> settle -> 200)
=========================================================================

This is the simplest "end-to-end" client example:
1) POST /v1/agent/trade  -> expects HTTP 402 with a payment challenge + job_id
2) POST /v1/agent/settle -> facilitator signs+sends SOL payment in-memory and unlocks output

IMPORTANT
- This example can broadcast a real SOL transaction when settlement is enabled.
- Set ATP_ALLOW_SPEND=true to actually run the settle step.

Env vars:
- ATP_BASE_URL      (default: http://localhost:8000)
- ATP_USER_WALLET   (required) payer public key string
- ATP_PRIVATE_KEY   (required) payer private key string (base58 keypair or JSON array of ints)
- ATP_ALLOW_SPEND   (default: false) set true to run settlement (spends SOL)
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

import httpx


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def main() -> int:
    base_url = os.getenv("ATP_BASE_URL", "http://localhost:8000").rstrip("/")
    user_wallet = os.getenv("ATP_USER_WALLET", "").strip()
    private_key = os.getenv("ATP_PRIVATE_KEY", "").strip()
    allow_spend = _bool_env("ATP_ALLOW_SPEND", default=False)

    if not user_wallet:
        raise RuntimeError("ATP_USER_WALLET is required")
    if not private_key:
        raise RuntimeError("ATP_PRIVATE_KEY is required")

    with httpx.Client(base_url=base_url, timeout=600.0) as client:
        # 0) Optional health check
        health = client.get("/health")
        health.raise_for_status()
        print("health:", health.json())

        # 1) Trade (expects 402 Payment Required)
        trade_payload: Dict[str, Any] = {
            "agent_config": {
                "agent_name": "atp-full-flow-example",
                "description": "Minimal end-to-end example",
                "model_name": "gpt-4.1",
                "max_loops": 1,
                "temperature": 0.0,
            },
            "task": "Return a short JSON object with keys: ok=true, note='hello from ATP'.",
            "user_wallet": user_wallet,
            "payment_token": "SOL",
        }
        trade = client.post("/v1/agent/trade", json=trade_payload)
        if trade.status_code != 402:
            raise RuntimeError(
                f"Expected HTTP 402 from /v1/agent/trade, got {trade.status_code}: {trade.text}"
            )

        challenge = trade.json()
        job_id = challenge.get("job_id")
        if not job_id:
            raise RuntimeError(f"Missing job_id in 402 response: {challenge}")

        print("\n--- 402 Payment Challenge ---")
        print(json.dumps(challenge, indent=2, sort_keys=False)[:4000])

        if not allow_spend:
            print(
                "\nSKIP settlement: set ATP_ALLOW_SPEND=true to run /v1/agent/settle (spends SOL)."
            )
            return 0

        # 2) Settle (expects 200 OK)
        settle_payload = {
            "job_id": job_id,
            "private_key": private_key,  # used in-memory only by the gateway
            "skip_preflight": False,
            "commitment": "confirmed",
        }
        settle = client.post("/v1/agent/settle", json=settle_payload)
        settle.raise_for_status()

        settled = settle.json()
        print("\n--- 200 Settlement Response ---")
        print(json.dumps(settled, indent=2, sort_keys=False)[:4000])

        return 0


if __name__ == "__main__":
    raise SystemExit(main())
