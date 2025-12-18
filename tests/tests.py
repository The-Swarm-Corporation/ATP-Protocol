"""
ATP Gateway - Comprehensive Integration Tests (httpx, no pytest/unittest)
========================================================================

Goals
-----
- Hit **real running endpoints** (no mocks).
- Cover **every API endpoint** in `atp/api.py` plus key negative/error cases.
- Optionally run the full **trade -> signed settle** flow which will
  broadcast a real SOL transaction (requires a funded wallet).

How to run
----------
1) Start the API (Docker or local), ensure it's reachable at ATP_BASE_URL.
2) Run:

    python tests/httpx_integration.py

Environment variables
---------------------
Required for basic endpoint checks:
- ATP_BASE_URL (default: http://localhost:8000)

Required for /v1/agent/trade (real upstream call):
- The running server must have SWARMS_API_KEY configured (server-side env).
- The running server must have AGENT_TREASURY_PUBKEY configured.

Required for full /v1/agent/settle (real SOL spend):
- ATP_USER_WALLET: payer pubkey string (must match the provided private key)
- ATP_PRIVATE_KEY: payer private key string (base58 keypair or JSON array of ints)
- ATP_ALLOW_SPEND: set to "true" to allow broadcasting a payment transaction

Safety controls (recommended):
- ATP_MAX_LAMPORTS: maximum lamports you allow the test to spend (default: 20000)
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, Optional

import httpx


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name, default)
    return v if v is not None and v != "" else None


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int) -> int:
    v = os.getenv(name)
    if not v:
        return default
    return int(v)


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def must_status(resp: httpx.Response, expected: int) -> Dict[str, Any]:
    check(
        resp.status_code == expected,
        f"Expected HTTP {expected}, got {resp.status_code}: {resp.text}",
    )
    if resp.content:
        return resp.json()
    return {}


def pretty(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2, sort_keys=False)[:5000]
    except Exception:
        return str(obj)[:5000]


def test_health(client: httpx.Client) -> None:
    r = client.get("/health")
    data = must_status(r, 200)
    check(data.get("status") == "healthy", f"/health unexpected: {pretty(data)}")


def test_token_price_and_payment_info(client: httpx.Client) -> None:
    # payment info
    info = must_status(client.get("/v1/payment/info"), 200)
    check("supported_tokens" in info, f"missing supported_tokens: {pretty(info)}")
    check("current_prices" in info, f"missing current_prices: {pretty(info)}")

    # token price: SOL
    sol = must_status(client.get("/v1/token/price/SOL"), 200)
    check(sol.get("token") == "SOL", f"bad SOL token price: {pretty(sol)}")
    check(
        isinstance(sol.get("price_usd"), (int, float)), f"bad price_usd: {pretty(sol)}"
    )

    # token price: USDC (pegged)
    usdc = must_status(client.get("/v1/token/price/USDC"), 200)
    check(usdc.get("token") == "USDC", f"bad USDC token price: {pretty(usdc)}")
    check(usdc.get("price_usd") == 1.0, f"USDC not pegged: {pretty(usdc)}")

    # invalid token
    bad = client.get("/v1/token/price/NOPE")
    check(
        bad.status_code == 400,
        f"Expected 400 for invalid token: {bad.status_code} {bad.text}",
    )

    # legacy endpoint
    legacy = must_status(client.get("/v1/sol/price"), 200)
    check(legacy.get("currency") == "SOL", f"bad legacy response: {pretty(legacy)}")


def test_settle_negative_cases(client: httpx.Client) -> None:
    # invalid job id
    r = client.post(
        "/v1/agent/settle", json={"job_id": "not-a-real-job", "private_key": "[1]"}
    )
    check(
        r.status_code in {400, 404},
        f"Expected 400/404 for fake job: {r.status_code} {r.text}",
    )

    # missing fields -> 422
    r2 = client.post("/v1/agent/settle", json={"job_id": "x"})
    check(
        r2.status_code == 422,
        f"Expected 422 for missing private_key: {r2.status_code} {r2.text}",
    )


def maybe_trade_and_settle(client: httpx.Client) -> None:
    """
    Runs the real trade flow (upstream Swarms call) and then real signed settlement.
    This WILL broadcast a real SOL transaction if enabled.
    """
    user_wallet = _env("ATP_USER_WALLET")
    private_key = _env("ATP_PRIVATE_KEY")
    allow_spend = _bool_env("ATP_ALLOW_SPEND", default=False)
    max_lamports = _int_env("ATP_MAX_LAMPORTS", default=20000)

    if not user_wallet:
        print("⏭️  SKIP trade/settle: ATP_USER_WALLET not set")
        return

    # Trade (expects 402)
    trade_payload = {
        "agent_config": {
            "agent_name": "atp-httpx-integration",
            "description": "Integration test invocation via ATP Gateway",
            "model_name": "gpt-4.1",
            "max_loops": 1,
            "temperature": 0.0,
        },
        "task": "Return a short JSON object with keys: ok=true, ts=<unix>.",
        "user_wallet": user_wallet,
        "payment_token": "SOL",
    }
    tr = client.post("/v1/agent/trade", json=trade_payload)
    data = must_status(tr, 402)
    job_id = data.get("job_id")
    check(job_id, f"Missing job_id from trade: {pretty(data)}")

    payment = data.get("payment") or {}
    lamports = payment.get("amount_lamports")
    check(
        isinstance(lamports, int), f"Expected integer amount_lamports: {pretty(data)}"
    )
    check(lamports > 0, f"Expected lamports > 0: {lamports}")
    check(
        lamports <= max_lamports,
        f"Refusing to spend {lamports} > ATP_MAX_LAMPORTS={max_lamports}",
    )

    if not allow_spend:
        print(
            f"⏭️  SKIP settle: would spend {lamports} lamports. Set ATP_ALLOW_SPEND=true to enable."
        )
        return
    if not private_key:
        raise RuntimeError("ATP_PRIVATE_KEY is required when ATP_ALLOW_SPEND=true")

    # Signed settle (expects 200)
    settle_payload = {
        "job_id": job_id,
        "private_key": private_key,
        "skip_preflight": False,
        "commitment": "confirmed",
    }
    st = client.post("/v1/agent/settle", json=settle_payload, timeout=600.0)
    out = must_status(st, 200)
    check(out.get("status") == "success", f"Bad settle response: {pretty(out)}")
    check(out.get("tx_signature"), f"Missing tx_signature: {pretty(out)}")
    check(out.get("agent_output") is not None, f"Missing agent_output: {pretty(out)}")


def main() -> int:
    base_url = (
        _env("ATP_BASE_URL", "https://atp-protocol-production.up.railway.app") or ""
    ).rstrip("/")
    print(f"ATP integration tests against: {base_url}")

    failures = []

    with httpx.Client(base_url=base_url, timeout=120.0) as client:
        for fn in [
            test_health,
            test_token_price_and_payment_info,
            test_settle_negative_cases,
            maybe_trade_and_settle,
        ]:
            name = fn.__name__
            t0 = time.time()
            try:
                fn(client)
                dt = (time.time() - t0) * 1000
                print(f"✅ PASS {name} ({dt:.0f}ms)")
            except Exception as e:
                dt = (time.time() - t0) * 1000
                print(f"❌ FAIL {name} ({dt:.0f}ms): {e}")
                failures.append((name, str(e)))

    if failures:
        print("\n❌ Failures:")
        for name, err in failures:
            print(f"- ❌ {name}: {err}")
        return 1

    print("\n✅ All tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
