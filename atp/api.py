"""
ATP Gateway FastAPI app.

Core flow:
- POST /v1/agent/trade  -> executes upstream agent and returns HTTP 402 challenge with a job_id + payment details
- POST /v1/agent/settle -> facilitator signs+sends payment (currently SOL-only) and unlocks the stored output

Important environment variables (server-side):
- SWARMS_API_KEY: used to call the upstream Swarms agent API
- AGENT_TREASURY_PUBKEY: payment recipient for the 402 challenge
- REDIS_URL: job vault storage (unless JOB_VAULT_BACKEND=memory)
- INPUT_COST_PER_MILLION_USD / OUTPUT_COST_PER_MILLION_USD: optional deterministic pricing from token counts
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict

import httpx
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from loguru import logger

from atp import config
from atp.schemas import AgentTask, PaymentToken, SettleTrade
from atp.solana_utils import (
    parse_keypair_from_string,
    send_and_confirm_sol_payment,
    verify_solana_transaction,
)
from atp.token_prices import token_price_fetcher
from atp.utils import calculate_payment_amounts, compute_usd_cost_from_usage
from atp.vault import InMemoryVault, RedisVault

# --- JOB VAULT INIT ---
job_vault: Any
if config.JOB_VAULT_BACKEND == "memory":
    job_vault = InMemoryVault(default_ttl=config.JOB_TTL_SECONDS)
else:
    job_vault = RedisVault(
        redis_url=config.REDIS_URL, default_ttl=config.JOB_TTL_SECONDS
    )


# --- APP LIFECYCLE ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan manager.

    Responsibilities:
    - Connect to the configured job vault (Redis by default).
    - Optionally fall back to an in-memory vault when Redis is unavailable
      (controlled by JOB_VAULT_BACKEND and FALLBACK_TO_MEMORY_VAULT).
    """
    global job_vault

    logger.info("Starting ATP Protocol Gateway")
    try:
        await job_vault.connect()
    except Exception as e:
        if config.JOB_VAULT_BACKEND == "redis" and config.FALLBACK_TO_MEMORY_VAULT:
            logger.warning(
                f"Redis unavailable ({e}). Falling back to in-memory job vault. "
                "For production, configure Redis or set FALLBACK_TO_MEMORY_VAULT=false."
            )
            job_vault = InMemoryVault(default_ttl=config.JOB_TTL_SECONDS)
            await job_vault.connect()
        else:
            raise

    yield

    logger.info("Shutting down ATP Protocol Gateway")
    await job_vault.disconnect()


app = FastAPI(
    title="Agentic Trade Protocol Gateway",
    description="A payment-gated API gateway for AI agent execution with Solana-based settlement",
    version="1.0.0",
    lifespan=lifespan,
)


# --- ENDPOINTS ---
@app.get("/health")
async def health_check():
    """Health check endpoint for load balancers and deployments."""
    return {"status": "healthy", "service": "ATP Protocol Gateway"}


@app.post("/v1/agent/trade", status_code=status.HTTP_402_PAYMENT_REQUIRED)
async def create_agent_trade(request: AgentTask):
    """Execute the upstream agent and return a payment challenge (HTTP 402).

    Behavior:
    - Calls the upstream Swarms agent completion endpoint immediately.
    - Computes `usd_cost`:
      - Prefer: from usage token counts using INPUT/OUTPUT_COST_PER_MILLION_USD
      - Fallback: upstream `usage.total_cost`
      - Final fallback: small constant for dev/demo
    - Converts USD -> SOL/USDC using the token price (SOL from CoinGecko, USDC pegged).
    - Stores the full agent result in the job vault under `job_id` until TTL expires.

    Returns:
    - HTTP 402 with JSON containing:
      - job_id
      - pricing breakdown
      - payment instructions (recipient, amount, memo)
      - fee breakdown (5% settlement fee)

    Required server config:
    - AGENT_TREASURY_PUBKEY must be set.
    """
    if not config.AGENT_TREASURY_PUBKEY:
        raise HTTPException(status_code=500, detail="Treasury not configured")

    logger.info(
        f"Processing trade request for agent: {request.agent_config.agent_name}"
    )
    logger.info(f"Payment token: {request.payment_token.value}")

    token_price_usd = await token_price_fetcher.get_price_usd(
        request.payment_token.value
    )

    # Execute Swarms Agent
    async with httpx.AsyncClient() as client:
        agent_config_dict = request.agent_config.model_dump(exclude_none=True)
        payload: Dict[str, Any] = {
            "agent_config": agent_config_dict,
            "task": request.task,
        }
        if request.history:
            payload["history"] = request.history
        if request.img:
            payload["img"] = request.img
        if request.imgs:
            payload["imgs"] = request.imgs

        headers = {
            "x-api-key": config.SWARMS_API_KEY,
            "Content-Type": "application/json",
        }
        try:
            swarms_resp = await client.post(
                config.SWARMS_API_URL, json=payload, headers=headers, timeout=120.0
            )
            if swarms_resp.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"Upstream Agent Error: {swarms_resp.status_code}",
                )
            data = swarms_resp.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Agent execution timed out")
        except httpx.RequestError:
            raise HTTPException(
                status_code=502, detail="Failed to connect to agent service"
            )

    usage = data.get("usage") or {}
    pricing = compute_usd_cost_from_usage(usage)
    usd_cost = float(pricing["usd_cost"])

    payment_amounts = calculate_payment_amounts(
        usd_cost, token_price_usd, request.payment_token
    )

    job_id = str(uuid.uuid4())
    job_data = {
        "result": data,
        "total_amount_units": payment_amounts["total_amount_units"],
        "agent_amount_units": payment_amounts["agent_amount_units"],
        "fee_amount_units": payment_amounts["fee_amount_units"],
        "sender": request.user_wallet,
        "usd_cost": usd_cost,
        "pricing": pricing,
        "token_price_at_creation": token_price_usd,
        "payment_token": request.payment_token.value,
    }

    await job_vault.store(job_id, job_data, ttl=config.JOB_TTL_SECONDS)

    if request.payment_token == PaymentToken.SOL:
        unit_name = "lamports"
        token_key = "sol"
    else:
        unit_name = "usdc_units"
        token_key = "usdc"

    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content={
            "job_id": job_id,
            "payment_token": request.payment_token.value,
            "pricing": pricing,
            "payment": {
                "description": "Send payment to the agent treasury. A 5% settlement fee will be automatically deducted.",
                f"amount_{unit_name}": payment_amounts["total_amount_units"],
                f"amount_{token_key}": payment_amounts["total_amount_token"],
                "amount_usd": usd_cost,
                "recipient": config.AGENT_TREASURY_PUBKEY,
                "memo": f"ATP:{job_id}",
            },
            "fee_breakdown": {
                "settlement_fee_percent": payment_amounts["fee_percent"],
                f"fee_{unit_name}": payment_amounts["fee_amount_units"],
                f"fee_{token_key}": payment_amounts["fee_amount_token"],
                "fee_usd": usd_cost * config.SETTLEMENT_FEE_PERCENT,
                "fee_recipient": config.SWARMS_TREASURY_PUBKEY,
                f"agent_receives_{unit_name}": payment_amounts["agent_amount_units"],
                f"agent_receives_{token_key}": payment_amounts["agent_amount_token"],
                "agent_receives_usd": usd_cost * (1 - config.SETTLEMENT_FEE_PERCENT),
            },
            "token_price_usd": token_price_usd,
            "usdc_mint": (
                config.USDC_MINT_ADDRESS
                if request.payment_token == PaymentToken.USDC
                else None
            ),
            "ttl_seconds": config.JOB_TTL_SECONDS,
            "instruction": (
                "To unlock the agent output, POST your private_key to /v1/agent/settle "
                "along with the job_id. The gateway will sign+send the SOL payment transaction "
                "in-memory (no persistence) and release the result after confirmation."
            ),
        },
    )


@app.post("/v1/agent/settle")
async def settle_agent_trade(request: SettleTrade):
    """Settle a pending trade by signing+sending payment and releasing output.

    Flow:
    - Loads the pending job by `job_id` from the job vault.
    - Validates that the provided private key corresponds to the job's `user_wallet`.
    - Builds/signs/sends a SOL transfer to `AGENT_TREASURY_PUBKEY` for the required lamports.
    - Verifies the on-chain signature (best-effort).
    - Pops (consumes) the job output exactly once and returns it.

    Notes:
    - This endpoint uses the private key in-memory only and does not persist it.
    - Currently supports signed settlement for SOL only.
    """
    job = await job_vault.retrieve(request.job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Trade session expired or invalid. Jobs expire after the TTL period.",
        )

    payment_token = PaymentToken(job.get("payment_token", "SOL"))
    if payment_token != PaymentToken.SOL:
        raise HTTPException(
            status_code=400,
            detail="Signed settlement currently supports SOL only.",
        )

    try:
        payer = parse_keypair_from_string(request.private_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid private_key: {str(e)}")

    payer_pubkey_str = str(payer.pubkey())
    expected_sender = job.get("sender")
    if expected_sender and payer_pubkey_str != expected_sender:
        raise HTTPException(
            status_code=400,
            detail="Payer mismatch: private key does not correspond to the job sender wallet.",
        )

    try:
        tx_sig = await send_and_confirm_sol_payment(
            payer=payer,
            recipient_pubkey_str=config.AGENT_TREASURY_PUBKEY,
            lamports=int(job["total_amount_units"]),
            skip_preflight=request.skip_preflight,
            commitment=request.commitment,
        )
    finally:
        request.private_key = ""

    # solana-py / solders may return Signature objects in some environments; ensure JSON-safe.
    tx_sig = str(tx_sig).strip()

    is_valid, msg = await verify_solana_transaction(
        tx_sig,
        job["total_amount_units"],
        payer_pubkey_str,
        payment_token,
        expected_recipient=config.AGENT_TREASURY_PUBKEY,
        commitment=request.commitment,
    )
    if not is_valid:
        raise HTTPException(
            status_code=400, detail=f"Payment verification failed: {msg}"
        )

    final_output = await job_vault.pop(request.job_id)
    if not final_output:
        raise HTTPException(
            status_code=409, detail="Trade was already settled or expired"
        )

    return {
        "status": "success",
        "job_id": request.job_id,
        "tx_signature": tx_sig,
        "agent_output": final_output["result"].get("outputs"),
        "usage": final_output["result"].get("usage"),
    }


@app.get("/v1/token/price/{token}")
async def get_token_price(token: str = "SOL"):
    """Get current token price in USD.

    - SOL uses CoinGecko (cached).
    - USDC is treated as $1.00 (pegged).
    """
    token_upper = token.upper()
    if token_upper not in config.SUPPORTED_PAYMENT_TOKENS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported token: {token}. Supported tokens: {config.SUPPORTED_PAYMENT_TOKENS}",
        )

    price = await token_price_fetcher.get_price_usd(token_upper)
    return {
        "token": token_upper,
        "price_usd": price,
        "source": "coingecko" if token_upper == "SOL" else "pegged",
        "mint_address": config.USDC_MINT_ADDRESS if token_upper == "USDC" else None,
    }


@app.get("/v1/sol/price")
async def get_sol_price():
    """Legacy endpoint: Get current SOL price in USD."""
    price = await token_price_fetcher.get_sol_price_usd()
    return {"currency": "SOL", "price_usd": price, "source": "coingecko"}


@app.get("/v1/payment/info")
async def get_payment_info():
    """Return supported tokens and the server's pricing/fee configuration."""
    sol_price = await token_price_fetcher.get_sol_price_usd()
    return {
        "supported_tokens": config.SUPPORTED_PAYMENT_TOKENS,
        "settlement_fee_percent": config.SETTLEMENT_FEE_PERCENT * 100,
        "swarms_treasury": config.SWARMS_TREASURY_PUBKEY,
        "agent_pricing": {
            "input_cost_per_million_usd": config.INPUT_COST_PER_MILLION_USD,
            "output_cost_per_million_usd": config.OUTPUT_COST_PER_MILLION_USD,
            "enabled": config.INPUT_COST_PER_MILLION_USD is not None
            or config.OUTPUT_COST_PER_MILLION_USD is not None,
        },
        "usdc_mint_address": config.USDC_MINT_ADDRESS,
        "usdc_decimals": config.USDC_DECIMALS,
        "sol_decimals": 9,
        "current_prices": {"SOL": sol_price, "USDC": 1.0},
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
