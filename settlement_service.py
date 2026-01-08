"""
ATP Settlement Service - FastAPI server for immutable settlement logic.

This service provides a centralized, immutable settlement API that handles:
- Usage token parsing from various API formats
- Payment amount calculation
- Solana payment execution
- Settlement verification

The service is designed to be stateless and immutable - all configuration
comes from environment variables or request parameters. No mutable state
is maintained in the settlement logic itself.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel, Field

from atp import config
from atp.schemas import PaymentToken
from atp.solana_utils import (
    parse_keypair_from_string,
    send_and_confirm_split_sol_payment,
)
from atp.token_prices import token_price_fetcher
from atp.utils import (
    calculate_payment_amounts,
    extract_usage_token_counts,
)


# Create FastAPI app for settlement service
app = FastAPI(
    title="ATP Settlement Service",
    description="Immutable settlement logic service for ATP Protocol",
    version="1.0.0",
)


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request/Response Schemas ---


class ParseUsageRequest(BaseModel):
    """Request to parse usage tokens from various formats."""

    usage_data: Dict[str, Any] = Field(
        ..., description="Usage data in any supported format"
    )


class ParseUsageResponse(BaseModel):
    """Response containing parsed usage tokens."""

    input_tokens: Optional[int] = Field(
        None, description="Number of input tokens"
    )
    output_tokens: Optional[int] = Field(
        None, description="Number of output tokens"
    )
    total_tokens: Optional[int] = Field(
        None, description="Total number of tokens"
    )


class CalculatePaymentRequest(BaseModel):
    """Request to calculate payment amounts from usage."""

    usage: Dict[str, Any] = Field(
        ..., description="Usage data containing token counts"
    )
    input_cost_per_million_usd: float = Field(
        ..., description="Cost per million input tokens in USD"
    )
    output_cost_per_million_usd: float = Field(
        ..., description="Cost per million output tokens in USD"
    )
    payment_token: PaymentToken = Field(
        default=PaymentToken.SOL,
        description="Token to use for payment (SOL or USDC)",
    )


class PricingInfo(BaseModel):
    """Pricing information for payment calculation."""

    usd_cost: float = Field(..., description="Total cost in USD")
    source: str = Field(
        ..., description="Source of pricing information"
    )
    input_tokens: Optional[int] = Field(
        None, description="Number of input tokens"
    )
    output_tokens: Optional[int] = Field(
        None, description="Number of output tokens"
    )
    total_tokens: Optional[int] = Field(
        None, description="Total number of tokens"
    )
    input_cost_per_million_usd: float = Field(
        ..., description="Cost per million input tokens in USD"
    )
    output_cost_per_million_usd: float = Field(
        ..., description="Cost per million output tokens in USD"
    )
    input_cost_usd: float = Field(
        ..., description="Input cost in USD"
    )
    output_cost_usd: float = Field(
        ..., description="Output cost in USD"
    )


class PaymentAmounts(BaseModel):
    """Payment amounts in different units."""

    total_amount_units: int = Field(
        ..., description="Total amount in base units (lamports)"
    )
    total_amount_token: float = Field(
        ..., description="Total amount in token units (SOL/USDC)"
    )
    fee_amount_units: int = Field(
        ..., description="Fee amount in base units"
    )
    fee_amount_token: float = Field(
        ..., description="Fee amount in token units"
    )
    agent_amount_units: int = Field(
        ..., description="Agent amount in base units"
    )
    agent_amount_token: float = Field(
        ..., description="Agent amount in token units"
    )


class CalculatePaymentResponse(BaseModel):
    """Response containing payment calculation details."""

    status: str = Field(
        ..., description="Status: 'calculated' or 'skipped'"
    )
    reason: Optional[str] = Field(
        None, description="Reason if skipped"
    )
    pricing: PricingInfo = Field(
        ..., description="Pricing information"
    )
    payment_amounts: Optional[PaymentAmounts] = Field(
        None, description="Payment amounts if calculated"
    )
    token_price_usd: Optional[float] = Field(
        None, description="Token price in USD"
    )


class SettlePaymentRequest(BaseModel):
    """Request to execute a settlement payment."""

    private_key: str = Field(
        ...,
        description=(
            "Solana wallet private key (JSON array format or base58 string). "
            "WARNING: This is custodial-like behavior. The private key is used "
            "in-memory only for the duration of this request and is not persisted."
        ),
    )
    usage: Dict[str, Any] = Field(
        ..., description="Usage data containing token counts"
    )
    input_cost_per_million_usd: float = Field(
        ..., description="Cost per million input tokens in USD"
    )
    output_cost_per_million_usd: float = Field(
        ..., description="Cost per million output tokens in USD"
    )
    recipient_pubkey: str = Field(
        ..., description="Solana public key of the recipient wallet"
    )
    payment_token: PaymentToken = Field(
        default=PaymentToken.SOL,
        description="Token to use for payment (SOL or USDC)",
    )
    treasury_pubkey: Optional[str] = Field(
        None,
        description="Treasury pubkey for processing fee (defaults to config)",
    )
    skip_preflight: bool = Field(
        default=False,
        description="Whether to skip preflight simulation",
    )
    commitment: str = Field(
        default="confirmed",
        description="Solana commitment level (processed|confirmed|finalized)",
    )


class TreasuryPayment(BaseModel):
    """Treasury payment details."""

    pubkey: str = Field(..., description="Treasury public key")
    amount_lamports: int = Field(
        ..., description="Amount in lamports"
    )
    amount_sol: float = Field(..., description="Amount in SOL")
    amount_usd: float = Field(..., description="Amount in USD")


class RecipientPayment(BaseModel):
    """Recipient payment details."""

    pubkey: str = Field(..., description="Recipient public key")
    amount_lamports: int = Field(
        ..., description="Amount in lamports"
    )
    amount_sol: float = Field(..., description="Amount in SOL")
    amount_usd: float = Field(..., description="Amount in USD")


class PaymentDetails(BaseModel):
    """Complete payment details."""

    total_amount_lamports: int = Field(
        ..., description="Total amount in lamports"
    )
    total_amount_sol: float = Field(
        ..., description="Total amount in SOL"
    )
    total_amount_usd: float = Field(
        ..., description="Total amount in USD"
    )
    treasury: TreasuryPayment = Field(
        ..., description="Treasury payment details"
    )
    recipient: RecipientPayment = Field(
        ..., description="Recipient payment details"
    )


class SettlePaymentResponse(BaseModel):
    """Response containing settlement payment details."""

    status: str = Field(
        ..., description="Status: 'paid' or 'skipped'"
    )
    transaction_signature: Optional[str] = Field(
        None, description="Transaction signature if paid"
    )
    pricing: PricingInfo = Field(
        ..., description="Pricing information"
    )
    payment: Optional[PaymentDetails] = Field(
        None, description="Payment details if paid"
    )


# --- Core Settlement Logic (Immutable) ---


def _safe_int(value: Any) -> Optional[int]:
    """Safely convert value to int."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None
    return None


def parse_usage_tokens(
    usage_data: Dict[str, Any],
) -> Dict[str, Optional[int]]:
    """
    Parse usage tokens from various API formats (immutable function).

    Supports multiple formats:
    - OpenAI: prompt_tokens, completion_tokens, total_tokens
    - Anthropic: input_tokens, output_tokens
    - Google/Gemini: promptTokenCount, candidatesTokenCount, totalTokenCount
    - Cohere: tokens (input + output), or input_tokens/output_tokens
    - Generic: input_tokens, output_tokens, total_tokens
    - Usage object: usage.prompt_tokens, usage.completion_tokens

    Args:
        usage_data: Dictionary containing usage information in any supported format.

    Returns:
        Dict with normalized keys: input_tokens, output_tokens, total_tokens
    """
    if not isinstance(usage_data, dict):
        return {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }

    # Try OpenAI format: prompt_tokens, completion_tokens, total_tokens
    prompt_tokens = _safe_int(usage_data.get("prompt_tokens"))
    completion_tokens = _safe_int(usage_data.get("completion_tokens"))
    total_tokens = _safe_int(usage_data.get("total_tokens"))

    if prompt_tokens is not None or completion_tokens is not None:
        return {
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "total_tokens": total_tokens
            or (
                (prompt_tokens or 0) + (completion_tokens or 0)
                if (
                    prompt_tokens is not None
                    or completion_tokens is not None
                )
                else None
            ),
        }

    # Try Anthropic/Generic format: input_tokens, output_tokens, total_tokens
    input_tokens = _safe_int(usage_data.get("input_tokens"))
    output_tokens = _safe_int(usage_data.get("output_tokens"))
    total_tokens_anthropic = _safe_int(usage_data.get("total_tokens"))

    if input_tokens is not None or output_tokens is not None:
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens_anthropic
            or (
                (input_tokens or 0) + (output_tokens or 0)
                if (
                    input_tokens is not None
                    or output_tokens is not None
                )
                else None
            ),
        }

    # Try Google/Gemini format: promptTokenCount, candidatesTokenCount, totalTokenCount
    prompt_token_count = _safe_int(usage_data.get("promptTokenCount"))
    candidates_token_count = _safe_int(
        usage_data.get("candidatesTokenCount")
    )
    total_token_count = _safe_int(usage_data.get("totalTokenCount"))

    if (
        prompt_token_count is not None
        or candidates_token_count is not None
    ):
        return {
            "input_tokens": prompt_token_count,
            "output_tokens": candidates_token_count,
            "total_tokens": total_token_count
            or (
                (prompt_token_count or 0)
                + (candidates_token_count or 0)
                if (
                    prompt_token_count is not None
                    or candidates_token_count is not None
                )
                else None
            ),
        }

    # Try Cohere format: tokens (total), or input_tokens/output_tokens separately
    cohere_tokens = _safe_int(usage_data.get("tokens"))
    cohere_input = _safe_int(usage_data.get("input_tokens"))
    cohere_output = _safe_int(usage_data.get("output_tokens"))

    if cohere_tokens is not None:
        return {
            "input_tokens": cohere_input,
            "output_tokens": cohere_output,
            "total_tokens": cohere_tokens,
        }

    # Try nested usage object (e.g., response.usage.prompt_tokens)
    if "usage" in usage_data and isinstance(
        usage_data["usage"], dict
    ):
        return parse_usage_tokens(usage_data["usage"])

    # Try meta.usage format (some APIs nest it)
    if "meta" in usage_data and isinstance(usage_data["meta"], dict):
        meta_usage = usage_data["meta"].get("usage")
        if isinstance(meta_usage, dict):
            return parse_usage_tokens(meta_usage)

    # Try statistics format (some APIs use this)
    if "statistics" in usage_data and isinstance(
        usage_data["statistics"], dict
    ):
        stats = usage_data["statistics"]
        return {
            "input_tokens": _safe_int(
                stats.get("input_tokens")
                or stats.get("prompt_tokens")
                or stats.get("tokens_in")
            ),
            "output_tokens": _safe_int(
                stats.get("output_tokens")
                or stats.get("completion_tokens")
                or stats.get("tokens_out")
            ),
            "total_tokens": _safe_int(
                stats.get("total_tokens") or stats.get("tokens")
            ),
        }

    # Fallback: return None for all if no recognized format found
    return {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


async def calculate_payment_from_usage(
    usage: Dict[str, Any],
    input_cost_per_million_usd: float,
    output_cost_per_million_usd: float,
    payment_token: PaymentToken = PaymentToken.SOL,
) -> Dict[str, Any]:
    """
    Calculate payment amounts from usage data (immutable function).

    Args:
        usage: Usage data containing token counts.
        input_cost_per_million_usd: Cost per million input tokens in USD.
        output_cost_per_million_usd: Cost per million output tokens in USD.
        payment_token: Token to use for payment (SOL or USDC).

    Returns:
        Dict with payment calculation details.
    """
    # Parse usage tokens
    parsed_tokens = parse_usage_tokens(usage)

    # Use extract_usage_token_counts as fallback for compatibility
    token_counts = extract_usage_token_counts(usage)

    # Prefer parsed tokens if available
    if parsed_tokens["input_tokens"] is not None:
        token_counts["input_tokens"] = parsed_tokens["input_tokens"]
    if parsed_tokens["output_tokens"] is not None:
        token_counts["output_tokens"] = parsed_tokens["output_tokens"]
    if parsed_tokens["total_tokens"] is not None:
        token_counts["total_tokens"] = parsed_tokens["total_tokens"]

    # Calculate cost using the provided rates
    usd_cost = 0.0
    pricing = {
        "usd_cost": 0.0,
        "source": "settlement_service_rates",
        "input_tokens": token_counts["input_tokens"],
        "output_tokens": token_counts["output_tokens"],
        "total_tokens": token_counts["total_tokens"],
        "input_cost_per_million_usd": input_cost_per_million_usd,
        "output_cost_per_million_usd": output_cost_per_million_usd,
        "input_cost_usd": 0.0,
        "output_cost_usd": 0.0,
    }

    if (
        token_counts["input_tokens"] is not None
        or token_counts["output_tokens"] is not None
    ):
        input_cost = (
            (token_counts["input_tokens"] or 0)
            / 1_000_000.0
            * input_cost_per_million_usd
        )
        output_cost = (
            (token_counts["output_tokens"] or 0)
            / 1_000_000.0
            * output_cost_per_million_usd
        )
        usd_cost = float(input_cost + output_cost)
        pricing.update(
            {
                "usd_cost": usd_cost,
                "input_cost_usd": input_cost,
                "output_cost_usd": output_cost,
            }
        )

    if usd_cost <= 0:
        return {
            "status": "skipped",
            "reason": "zero_cost",
            "pricing": pricing,
            "payment_amounts": None,
        }

    # Get token price
    token_price_usd = await token_price_fetcher.get_price_usd(
        payment_token.value
    )

    # Calculate payment amounts
    payment_amounts = calculate_payment_amounts(
        usd_cost, token_price_usd, payment_token
    )

    return {
        "status": "calculated",
        "pricing": pricing,
        "payment_amounts": payment_amounts,
        "token_price_usd": token_price_usd,
    }


async def execute_settlement(
    private_key: str,
    usage: Dict[str, Any],
    input_cost_per_million_usd: float,
    output_cost_per_million_usd: float,
    recipient_pubkey: str,
    payment_token: PaymentToken = PaymentToken.SOL,
    treasury_pubkey: Optional[str] = None,
    skip_preflight: bool = False,
    commitment: str = "confirmed",
) -> Dict[str, Any]:
    """
    Execute a settlement payment (immutable function).

    Args:
        private_key: Solana wallet private key (JSON array format or base58 string).
        usage: Usage data containing token counts.
        input_cost_per_million_usd: Cost per million input tokens in USD.
        output_cost_per_million_usd: Cost per million output tokens in USD.
        recipient_pubkey: Solana public key of the recipient wallet.
        payment_token: Token to use for payment (SOL or USDC).
        treasury_pubkey: Treasury pubkey for processing fee (defaults to config).
        skip_preflight: Whether to skip preflight simulation.
        commitment: Solana commitment level (processed|confirmed|finalized).

    Returns:
        Dict with payment details including transaction signature.
    """
    # Calculate payment
    payment_calc = await calculate_payment_from_usage(
        usage,
        input_cost_per_million_usd,
        output_cost_per_million_usd,
        payment_token,
    )

    if payment_calc["status"] == "skipped":
        return payment_calc

    payment_amounts = payment_calc["payment_amounts"]
    pricing = payment_calc["pricing"]
    usd_cost = pricing["usd_cost"]

    # Validate payment token support
    if payment_token != PaymentToken.SOL:
        raise HTTPException(
            status_code=400,
            detail=f"Automatic settlement currently supports SOL only. Requested: {payment_token.value}",
        )

    # Parse keypair
    try:
        payer = parse_keypair_from_string(private_key)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse wallet private key: {str(e)}",
        )

    # Use treasury from config if not provided
    treasury_pubkey_str = (
        treasury_pubkey or config.SWARMS_TREASURY_PUBKEY
    )
    if not treasury_pubkey_str:
        raise HTTPException(
            status_code=500,
            detail="Treasury pubkey not configured",
        )

    # Execute split payment: treasury gets fee, recipient gets the rest
    try:
        treasury_lamports = int(payment_amounts["fee_amount_units"])
        recipient_lamports = int(
            payment_amounts["agent_amount_units"]
        )

        tx_sig = await send_and_confirm_split_sol_payment(
            payer=payer,
            treasury_pubkey_str=treasury_pubkey_str,
            recipient_pubkey_str=recipient_pubkey,
            treasury_lamports=treasury_lamports,
            recipient_lamports=recipient_lamports,
            skip_preflight=skip_preflight,
            commitment=commitment,
        )
        tx_sig = str(tx_sig).strip()

        return {
            "status": "paid",
            "transaction_signature": tx_sig,
            "pricing": pricing,
            "payment": {
                "total_amount_lamports": payment_amounts[
                    "total_amount_units"
                ],
                "total_amount_sol": payment_amounts[
                    "total_amount_token"
                ],
                "total_amount_usd": usd_cost,
                "treasury": {
                    "pubkey": treasury_pubkey_str,
                    "amount_lamports": treasury_lamports,
                    "amount_sol": payment_amounts["fee_amount_token"],
                    "amount_usd": usd_cost
                    * config.SETTLEMENT_FEE_PERCENT,
                },
                "recipient": {
                    "pubkey": recipient_pubkey,
                    "amount_lamports": recipient_lamports,
                    "amount_sol": payment_amounts[
                        "agent_amount_token"
                    ],
                    "amount_usd": usd_cost
                    * (1 - config.SETTLEMENT_FEE_PERCENT),
                },
            },
        }
    except Exception as e:
        logger.error(f"Payment deduction failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to deduct payment: {str(e)}",
        )


# --- FastAPI Endpoints ---


@app.get(
    "/health",
    tags=["Health"],
    summary="Health Check",
    description="Check the health status of the ATP Settlement Service",
    response_description="Service health status and version information",
    operation_id="health_check",
)
async def health_check():
    """
    Health check endpoint for monitoring service availability.

    Returns basic service information including status and version.
    """
    return {
        "status": "healthy",
        "service": "ATP Settlement Service",
        "version": "1.0.0",
    }


@app.post(
    "/v1/settlement/parse-usage",
    response_model=ParseUsageResponse,
    tags=["Settlement", "Usage Parsing"],
    summary="Parse Usage Tokens",
    description=(
        "Parse usage tokens from various API provider formats into a standardized format. "
        "Supports multiple formats including OpenAI, Anthropic, Google/Gemini, Cohere, and generic formats. "
        "The endpoint automatically detects the format and extracts input_tokens, output_tokens, and total_tokens."
    ),
    response_description="Parsed token counts in standardized format",
    operation_id="parse_usage_tokens",
)
async def parse_usage_endpoint(
    request: ParseUsageRequest,
) -> ParseUsageResponse:
    """
    Parse usage tokens from various API formats.

    This endpoint normalizes usage data from different API providers into a consistent format.
    It supports:
    - OpenAI: prompt_tokens, completion_tokens, total_tokens
    - Anthropic: input_tokens, output_tokens, total_tokens
    - Google/Gemini: promptTokenCount, candidatesTokenCount, totalTokenCount
    - Cohere: tokens, input_tokens, output_tokens
    - Generic: input_tokens, output_tokens, total_tokens
    - Nested formats: usage.usage, meta.usage, statistics

    Returns:
        ParseUsageResponse with parsed token counts (input_tokens, output_tokens, total_tokens)
    """
    parsed = parse_usage_tokens(request.usage_data)
    return ParseUsageResponse(**parsed)


@app.post(
    "/v1/settlement/calculate-payment",
    response_model=CalculatePaymentResponse,
    tags=["Settlement", "Payment Calculation"],
    summary="Calculate Payment Amounts",
    description=(
        "Calculate payment amounts from usage data based on token counts and pricing rates. "
        "This endpoint parses usage tokens, calculates USD costs, fetches current token prices, "
        "and computes payment amounts in the specified token (SOL or USDC). "
        "Returns detailed pricing breakdown including input/output costs and payment amounts. "
        "If the calculated cost is zero or negative, the payment is skipped."
    ),
    response_description=(
        "Payment calculation result with pricing details and payment amounts. "
        "Status will be 'calculated' if payment is required, or 'skipped' if cost is zero."
    ),
    operation_id="calculate_payment",
)
async def calculate_payment_endpoint(
    request: CalculatePaymentRequest,
) -> CalculatePaymentResponse:
    """
    Calculate payment amounts from usage data.

    This endpoint:
    1. Parses usage tokens from the provided usage data
    2. Calculates USD cost based on input/output token counts and pricing rates
    3. Fetches current token price (SOL or USDC) from price oracle
    4. Calculates payment amounts in the specified token
    5. Returns detailed breakdown including fees and agent amounts

    The calculation includes:
    - Input cost: (input_tokens / 1,000,000) * input_cost_per_million_usd
    - Output cost: (output_tokens / 1,000,000) * output_cost_per_million_usd
    - Total USD cost: input_cost + output_cost
    - Payment amounts split between treasury (fee) and agent (net payment)

    Returns:
        CalculatePaymentResponse with payment calculation details including:
        - Status: 'calculated' or 'skipped'
        - Pricing information with token counts and costs
        - Payment amounts in token units (if calculated)
        - Current token price in USD
    """
    result = await calculate_payment_from_usage(
        request.usage,
        request.input_cost_per_million_usd,
        request.output_cost_per_million_usd,
        request.payment_token,
    )

    # Convert dict result to Pydantic model
    if result["status"] == "skipped":
        return CalculatePaymentResponse(
            status=result["status"],
            reason=result.get("reason"),
            pricing=PricingInfo(**result["pricing"]),
            payment_amounts=None,
            token_price_usd=None,
        )

    return CalculatePaymentResponse(
        status=result["status"],
        reason=None,
        pricing=PricingInfo(**result["pricing"]),
        payment_amounts=(
            PaymentAmounts(**result["payment_amounts"])
            if result.get("payment_amounts")
            else None
        ),
        token_price_usd=result.get("token_price_usd"),
    )


@app.post(
    "/v1/settlement/settle",
    response_model=SettlePaymentResponse,
    tags=["Settlement", "Payment Execution"],
    summary="Execute Settlement Payment",
    description=(
        "Execute a complete settlement payment on Solana blockchain. "
        "This endpoint calculates payment amounts from usage data and executes a split payment transaction "
        "that sends funds to both the treasury (processing fee) and the recipient agent (net payment). "
        "The payment is executed as an atomic Solana transaction with automatic confirmation. "
        "WARNING: This endpoint requires the payer's private key and performs custodial-like behavior. "
        "The private key is used in-memory only and is never persisted."
    ),
    response_description=(
        "Settlement execution result with transaction signature and payment details. "
        "Status will be 'paid' if transaction was successful, or 'skipped' if cost is zero. "
        "Includes complete payment breakdown with treasury and recipient amounts."
    ),
    operation_id="settle_payment",
)
async def settle_endpoint(
    request: SettlePaymentRequest,
) -> SettlePaymentResponse:
    """
    Execute a settlement payment on Solana blockchain.

    This endpoint performs a complete settlement flow:
    1. Parses usage tokens from the provided usage data
    2. Calculates payment amounts based on pricing rates
    3. Fetches current token price (currently supports SOL only)
    4. Creates and signs a split payment transaction on Solana
    5. Sends the transaction and waits for confirmation
    6. Returns transaction signature and payment details

    The payment is split between:
    - Treasury: Receives the processing fee (configurable percentage)
    - Recipient: Receives the net payment amount after fees

    Transaction Details:
    - Uses Solana split payment mechanism for atomic execution
    - Supports preflight simulation (can be skipped for faster execution)
    - Configurable commitment level (processed/confirmed/finalized)
    - Returns transaction signature for blockchain verification

    Security Notes:
    - Private key is parsed from string format (base58 or JSON array)
    - Key is used only in-memory for transaction signing
    - No key material is logged or persisted
    - Transaction is executed on-chain with full transparency

    Returns:
        SettlePaymentResponse with:
        - Status: 'paid' if successful, 'skipped' if zero cost
        - Transaction signature: Solana transaction signature (if paid)
        - Pricing information: Complete cost breakdown
        - Payment details: Treasury and recipient payment amounts
    """
    result = await execute_settlement(
        private_key=request.private_key,
        usage=request.usage,
        input_cost_per_million_usd=request.input_cost_per_million_usd,
        output_cost_per_million_usd=request.output_cost_per_million_usd,
        recipient_pubkey=request.recipient_pubkey,
        payment_token=request.payment_token,
        treasury_pubkey=request.treasury_pubkey,
        skip_preflight=request.skip_preflight,
        commitment=request.commitment,
    )

    # Convert dict result to Pydantic model
    if result["status"] == "skipped":
        return SettlePaymentResponse(
            status=result["status"],
            transaction_signature=None,
            pricing=PricingInfo(**result["pricing"]),
            payment=None,
        )

    return SettlePaymentResponse(
        status=result["status"],
        transaction_signature=result.get("transaction_signature"),
        pricing=PricingInfo(**result["pricing"]),
        payment=(
            PaymentDetails(**result["payment"])
            if result.get("payment")
            else None
        ),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
