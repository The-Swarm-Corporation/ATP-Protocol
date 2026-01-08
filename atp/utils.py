from __future__ import annotations

from typing import Any, Dict, Optional

from atp import config
from atp.schemas import PaymentToken


def calculate_payment_amounts(
    usd_cost: float,
    token_price_usd: float,
    payment_token: PaymentToken,
) -> Dict[str, Any]:
    """
    Calculate payment amounts with settlement fee taken from the total.

    Returns amounts in the smallest unit (lamports for SOL, micro-units for USDC).
    """
    total_amount_token = usd_cost / token_price_usd
    fee_amount_token = (
        total_amount_token * config.SETTLEMENT_FEE_PERCENT
    )
    agent_amount_token = total_amount_token - fee_amount_token

    decimals = (
        9
        if payment_token == PaymentToken.SOL
        else config.USDC_DECIMALS
    )

    total_amount_units = int(total_amount_token * 10**decimals)
    fee_amount_units = int(fee_amount_token * 10**decimals)
    agent_amount_units = total_amount_units - fee_amount_units

    return {
        "total_amount_units": total_amount_units,
        "agent_amount_units": agent_amount_units,
        "fee_amount_units": fee_amount_units,
        "total_amount_token": total_amount_token,
        "agent_amount_token": agent_amount_token,
        "fee_amount_token": fee_amount_token,
        "decimals": decimals,
        "fee_percent": config.SETTLEMENT_FEE_PERCENT * 100,
    }


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return int(float(s))
        except Exception:
            return None
    return None


def extract_usage_token_counts(
    usage: Any,
) -> Dict[str, Optional[int]]:
    """
    Normalize token counts from various possible upstream shapes.
    Common keys:
    - prompt_tokens / completion_tokens / total_tokens (OpenAI-like)
    - input_tokens / output_tokens / total_tokens
    """
    if not isinstance(usage, dict):
        return {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }

    input_tokens = _safe_int(usage.get("input_tokens"))
    if input_tokens is None:
        input_tokens = _safe_int(usage.get("prompt_tokens"))

    output_tokens = _safe_int(usage.get("output_tokens"))
    if output_tokens is None:
        output_tokens = _safe_int(usage.get("completion_tokens"))

    total_tokens = _safe_int(usage.get("total_tokens"))
    if (
        total_tokens is None
        and input_tokens is not None
        and output_tokens is not None
    ):
        total_tokens = input_tokens + output_tokens

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def compute_usd_cost_from_usage(usage: Any) -> Dict[str, Any]:
    """
    Returns a pricing breakdown dict containing:
    - usd_cost (float)
    - source: per_million_rates | upstream_total_cost | fallback_default
    - token counts and configured rates
    """
    usage = usage if isinstance(usage, dict) else {}
    counts = extract_usage_token_counts(usage)

    can_compute_input = (
        config.INPUT_COST_PER_MILLION_USD is not None
        and counts["input_tokens"] is not None
    )
    can_compute_output = (
        config.OUTPUT_COST_PER_MILLION_USD is not None
        and counts["output_tokens"] is not None
    )

    if can_compute_input or can_compute_output:
        input_cost = (
            (counts["input_tokens"] or 0)
            / 1_000_000.0
            * (config.INPUT_COST_PER_MILLION_USD or 0.0)
        )
        output_cost = (
            (counts["output_tokens"] or 0)
            / 1_000_000.0
            * (config.OUTPUT_COST_PER_MILLION_USD or 0.0)
        )
        usd_cost = float(input_cost + output_cost)
        return {
            "usd_cost": usd_cost,
            "source": "per_million_rates",
            "input_tokens": counts["input_tokens"],
            "output_tokens": counts["output_tokens"],
            "total_tokens": counts["total_tokens"],
            "input_cost_per_million_usd": config.INPUT_COST_PER_MILLION_USD,
            "output_cost_per_million_usd": config.OUTPUT_COST_PER_MILLION_USD,
            "input_cost_usd": input_cost,
            "output_cost_usd": output_cost,
        }

    upstream_total_cost = usage.get("total_cost")
    try:
        if upstream_total_cost is not None:
            usd_cost = float(upstream_total_cost)
            return {
                "usd_cost": usd_cost,
                "source": "upstream_total_cost",
                "input_tokens": counts["input_tokens"],
                "output_tokens": counts["output_tokens"],
                "total_tokens": counts["total_tokens"],
                "input_cost_per_million_usd": config.INPUT_COST_PER_MILLION_USD,
                "output_cost_per_million_usd": config.OUTPUT_COST_PER_MILLION_USD,
            }
    except Exception:
        pass

    usd_cost = 0.01
    return {
        "usd_cost": usd_cost,
        "source": "fallback_default",
        "input_tokens": counts["input_tokens"],
        "output_tokens": counts["output_tokens"],
        "total_tokens": counts["total_tokens"],
        "input_cost_per_million_usd": config.INPUT_COST_PER_MILLION_USD,
        "output_cost_per_million_usd": config.OUTPUT_COST_PER_MILLION_USD,
    }
