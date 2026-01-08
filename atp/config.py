"""
Central configuration for the ATP Gateway.

Keep all env parsing + constants here so the rest of the code can be imported cleanly.
"""

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _float_env(name: str) -> Optional[float]:
    v = os.getenv(name)
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    return float(v)


SWARMS_API_KEY = os.getenv("SWARMS_API_KEY")
SWARMS_API_URL = os.getenv(
    "SWARMS_API_URL", "https://api.swarms.world/v1/agent/completions"
)

SOLANA_RPC_URL = os.getenv(
    "SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"
)
AGENT_TREASURY_PUBKEY = os.getenv("AGENT_TREASURY_PUBKEY")

JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", "600"))

# Swarms Treasury for settlement fees
SWARMS_TREASURY_PUBKEY = os.getenv(
    "SWARMS_TREASURY_PUBKEY",
    "7MaX4muAn8ZQREJxnupm8sgokwFHujgrGfH9Qn81BuEV",
)
SETTLEMENT_FEE_PERCENT = float(
    os.getenv("SETTLEMENT_FEE_PERCENT", "0.05")
)

# USDC Token Configuration (Solana Mainnet)
USDC_MINT_ADDRESS = os.getenv(
    "USDC_MINT_ADDRESS",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
)
USDC_DECIMALS = int(os.getenv("USDC_DECIMALS", "6"))

SUPPORTED_PAYMENT_TOKENS = ["SOL", "USDC"]

# Agent pricing configuration (host-provided)
INPUT_COST_PER_MILLION_USD = _float_env("INPUT_COST_PER_MILLION_USD")
OUTPUT_COST_PER_MILLION_USD = _float_env(
    "OUTPUT_COST_PER_MILLION_USD"
)

# Verbose Solana debug logging (server-side). Enable temporarily for diagnosing RPC type mismatches.
# WARNING: do not enable permanently in high-traffic production environments.
ATP_SOLANA_DEBUG = _bool_env("ATP_SOLANA_DEBUG", default=False)

# Settlement Service URL
ATP_SETTLEMENT_URL = os.getenv(
    "ATP_SETTLEMENT_URL", "http://localhost:8001"
)
