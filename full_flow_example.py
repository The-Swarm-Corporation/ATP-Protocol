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

from dotenv import load_dotenv

load_dotenv()


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _pretty(obj: Any, limit: int = 12000) -> str:
    try:
        s = json.dumps(obj, indent=2, sort_keys=False)
    except Exception:
        s = str(obj)
    return s if len(s) <= limit else s[:limit] + "\n... (truncated) ..."


def _print_section(title: str) -> None:
    bar = "=" * max(12, len(title))
    print(f"\n{bar}\n{title}\n{bar}")


def main() -> int:
    base_url = os.getenv(
        "ATP_BASE_URL", "https://atp-protocol-production.up.railway.app"
    ).rstrip("/")
    user_wallet = (os.getenv("ATP_USER_WALLET") or "").strip()
    private_key = (os.getenv("ATP_PRIVATE_KEY") or "").strip()
    allow_spend = _bool_env("ATP_ALLOW_SPEND", default=True)

    if not user_wallet:
        raise RuntimeError("ATP_USER_WALLET is required")
    if not private_key:
        raise RuntimeError("ATP_PRIVATE_KEY is required")

    _print_section("CONFIG")
    print("ATP_BASE_URL:", base_url)
    print("ATP_USER_WALLET:", user_wallet)
    print("ATP_ALLOW_SPEND:", allow_spend)
    print(
        "NOTE: private key is loaded from ATP_PRIVATE_KEY but will NOT be printed (redacted)."
    )
    if allow_spend:
        print(
            "WARNING: ATP_ALLOW_SPEND=true will broadcast a REAL SOL transaction if the server is configured for signed settlement."
        )

    with httpx.Client(base_url=base_url, timeout=600.0) as client:
        # 0) Optional health check
        _print_section("0) GET /health")
        health = client.get("/health")
        print("status:", health.status_code)
        print("body:", _pretty(health.json() if health.content else health.text))
        health.raise_for_status()

        # 1) Trade (expects 402 Payment Required)
        _print_section("1) POST /v1/agent/trade  (expect 402)")
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
        print("request payload:", _pretty(trade_payload))
        trade = client.post("/v1/agent/trade", json=trade_payload)
        print("status:", trade.status_code)
        try:
            trade_json = trade.json() if trade.content else {}
        except Exception:
            trade_json = {"raw_text": trade.text}
        print("response body:", _pretty(trade_json))

        if trade.status_code != 402:
            raise RuntimeError(
                f"Expected HTTP 402 from /v1/agent/trade, got {trade.status_code}: {trade.text}"
            )

        challenge = trade_json
        job_id = challenge.get("job_id")
        if not job_id:
            raise RuntimeError(f"Missing job_id in 402 response: {challenge}")

        _print_section("402 CHALLENGE SUMMARY")
        print("job_id:", job_id)
        print("payment_token:", challenge.get("payment_token"))
        if isinstance(challenge.get("pricing"), dict):
            print("pricing:", _pretty(challenge["pricing"]))
        if isinstance(challenge.get("payment"), dict):
            print("payment:", _pretty(challenge["payment"]))
        if isinstance(challenge.get("fee_breakdown"), dict):
            print("fee_breakdown:", _pretty(challenge["fee_breakdown"]))
        print("ttl_seconds:", challenge.get("ttl_seconds"))
        print("instruction:", challenge.get("instruction"))

        if not allow_spend:
            print(
                "\nSKIP settlement: set ATP_ALLOW_SPEND=true to run /v1/agent/settle (spends SOL)."
            )
            return 0

        # 2) Settle (expects 200 OK)
        _print_section("2) POST /v1/agent/settle  (expect 200)")
        settle_payload = {
            "job_id": job_id,
            "private_key": private_key,  # used in-memory only by the gateway (DO NOT print)
            "skip_preflight": False,
            "commitment": "confirmed",
        }
        settle_payload_printable = dict(settle_payload)
        settle_payload_printable["private_key"] = "<REDACTED>"
        print("request payload:", _pretty(settle_payload_printable))

        settle = client.post("/v1/agent/settle", json=settle_payload)
        print("status:", settle.status_code)
        try:
            settle_json = settle.json() if settle.content else {}
        except Exception:
            settle_json = {"raw_text": settle.text}
        print("response body:", _pretty(settle_json))

        settle.raise_for_status()

        settled = settle_json

        _print_section("SETTLEMENT SUMMARY")
        print("status:", settled.get("status"))
        print("job_id:", settled.get("job_id"))
        print("tx_signature:", settled.get("tx_signature"))
        print("usage:", _pretty(settled.get("usage")))
        print("agent_output:", _pretty(settled.get("agent_output")))

        return 0


if __name__ == "__main__":
    raise SystemExit(main())
