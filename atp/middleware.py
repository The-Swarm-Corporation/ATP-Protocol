"""
FastAPI middleware for ATP settlement on any endpoint.

This middleware enables automatic payment deduction from Solana wallets
based on token usage (input/output tokens) for any configured endpoint.

The middleware accepts wallet private keys directly via headers, making it
simple to use without requiring API key management. Users can add their
own API key handling layer if needed.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Set

from fastapi import HTTPException, Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

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


class ATPSettlementMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware that automatically deducts payment from Solana wallets
    based on token usage for configured endpoints.

    The middleware accepts wallet private keys directly via headers, making it
    simple to use. Users can add their own API key handling layer if needed.

    Payments are split automatically:
    - Treasury (SWARMS_TREASURY_PUBKEY) receives the processing fee
    - Recipient (endpoint host) receives the remainder

    Usage:
        app.add_middleware(
            ATPSettlementMiddleware,
            allowed_endpoints=["/v1/chat", "/v1/completions"],
            input_cost_per_million_usd=10.0,
            output_cost_per_million_usd=30.0,
            wallet_private_key_header="x-wallet-private-key",
            payment_token=PaymentToken.SOL,
            recipient_pubkey="YourPublicKeyHere",  # Required: endpoint host receives main payment
        )
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_endpoints: List[str],
        input_cost_per_million_usd: float,
        output_cost_per_million_usd: float,
        wallet_private_key_header: str = "x-wallet-private-key",
        payment_token: PaymentToken = PaymentToken.SOL,
        recipient_pubkey: Optional[str] = None,
        skip_preflight: bool = False,
        commitment: str = "confirmed",
        usage_response_key: str = "usage",
        include_usage_in_response: bool = True,
        require_wallet: bool = True,
    ):
        """
        Initialize the ATP settlement middleware.

        Args:
            app: The ASGI application.
            allowed_endpoints: List of endpoint paths to apply settlement to (e.g., ["/v1/chat"]).
                Supports path patterns - exact matches only.
            input_cost_per_million_usd: Cost per million input tokens in USD.
            output_cost_per_million_usd: Cost per million output tokens in USD.
            wallet_private_key_header: HTTP header name containing the wallet private key
                (default: "x-wallet-private-key"). The private key should be in JSON array
                format (e.g., "[1,2,3,...]") or base58 string format.
            payment_token: Token to use for payment (SOL or USDC).
            recipient_pubkey: Solana public key of the recipient wallet (the endpoint host).
                This wallet receives the main payment (after processing fee). Required.
            skip_preflight: Whether to skip preflight simulation for Solana transactions.
            commitment: Solana commitment level (processed|confirmed|finalized).
            usage_response_key: Key in response JSON where usage data is located (default: "usage").
            include_usage_in_response: Whether to add usage/cost info to the response.
            require_wallet: Whether to require wallet private key (if False, skips settlement when missing).
        """
        super().__init__(app)
        self.allowed_endpoints: Set[str] = set(allowed_endpoints)
        self.input_cost_per_million_usd = input_cost_per_million_usd
        self.output_cost_per_million_usd = output_cost_per_million_usd
        self.wallet_private_key_header = wallet_private_key_header.lower()
        self.payment_token = payment_token
        # Recipient pubkey - configurable, the endpoint host receives the main payment
        self._recipient_pubkey = recipient_pubkey
        if not self._recipient_pubkey:
            raise ValueError("recipient_pubkey must be provided")
        # Treasury pubkey - always uses SWARMS_TREASURY_PUBKEY for processing fees
        self._treasury_pubkey = config.SWARMS_TREASURY_PUBKEY
        if not self._treasury_pubkey:
            raise ValueError("SWARMS_TREASURY_PUBKEY must be set in configuration")
        self.skip_preflight = skip_preflight
        self.commitment = commitment
        self.usage_response_key = usage_response_key
        self.include_usage_in_response = include_usage_in_response
        self.require_wallet = require_wallet

    def _should_process(self, path: str) -> bool:
        """Check if the request path should be processed by this middleware."""
        return path in self.allowed_endpoints

    def _extract_wallet_private_key(self, request: Request) -> Optional[str]:
        """Extract wallet private key from request headers."""
        return request.headers.get(self.wallet_private_key_header)

    def _parse_usage_tokens(
        self, usage_data: Dict[str, Any]
    ) -> Dict[str, Optional[int]]:
        """
        Parse usage tokens from various API formats.

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
            return {"input_tokens": None, "output_tokens": None, "total_tokens": None}

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
                    if (prompt_tokens is not None or completion_tokens is not None)
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
                    if (input_tokens is not None or output_tokens is not None)
                    else None
                ),
            }

        # Try Google/Gemini format: promptTokenCount, candidatesTokenCount, totalTokenCount
        prompt_token_count = _safe_int(usage_data.get("promptTokenCount"))
        candidates_token_count = _safe_int(usage_data.get("candidatesTokenCount"))
        total_token_count = _safe_int(usage_data.get("totalTokenCount"))

        if prompt_token_count is not None or candidates_token_count is not None:
            return {
                "input_tokens": prompt_token_count,
                "output_tokens": candidates_token_count,
                "total_tokens": total_token_count
                or (
                    (prompt_token_count or 0) + (candidates_token_count or 0)
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
            # If only total tokens provided, we can't split it, so return None for input/output
            return {
                "input_tokens": cohere_input,
                "output_tokens": cohere_output,
                "total_tokens": cohere_tokens,
            }

        # Try nested usage object (e.g., response.usage.prompt_tokens)
        if "usage" in usage_data and isinstance(usage_data["usage"], dict):
            return self._parse_usage_tokens(usage_data["usage"])

        # Try meta.usage format (some APIs nest it)
        if "meta" in usage_data and isinstance(usage_data["meta"], dict):
            meta_usage = usage_data["meta"].get("usage")
            if isinstance(meta_usage, dict):
                return self._parse_usage_tokens(meta_usage)

        # Try statistics format (some APIs use this)
        if "statistics" in usage_data and isinstance(usage_data["statistics"], dict):
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
        return {"input_tokens": None, "output_tokens": None, "total_tokens": None}

    async def _extract_usage_from_response(
        self, response_body: bytes
    ) -> Optional[Dict[str, Any]]:
        """
        Extract usage information from response body.

        Tries multiple strategies:
        1. Look for usage data at the configured usage_response_key
        2. Check if the entire response contains usage-like keys
        3. Try nested structures (usage.usage, meta.usage, etc.)
        """
        try:
            body_str = response_body.decode("utf-8")
            if not body_str.strip():
                return None
            data = json.loads(body_str)

            # Strategy 1: Try the configured usage key first
            usage = data.get(self.usage_response_key)
            if usage:
                if isinstance(usage, dict):
                    # Parse it to normalize the format
                    parsed = self._parse_usage_tokens(usage)
                    # Return original dict but ensure it has the keys we need
                    return {**usage, **parsed}
                return None

            # Strategy 2: Check if the entire response is usage-like
            if isinstance(data, dict):
                # Check for common usage keys at top level
                usage_keys = [
                    "input_tokens",
                    "output_tokens",
                    "prompt_tokens",
                    "completion_tokens",
                    "total_tokens",
                    "tokens",
                    "promptTokenCount",
                    "candidatesTokenCount",
                    "totalTokenCount",
                ]
                if any(key in data for key in usage_keys):
                    parsed = self._parse_usage_tokens(data)
                    # Only return if we successfully parsed something
                    if (
                        parsed["input_tokens"] is not None
                        or parsed["output_tokens"] is not None
                    ):
                        return {**data, **parsed}

            # Strategy 3: Try nested structures
            # Check for usage nested in common locations
            for nested_key in ["usage", "token_usage", "tokens", "statistics", "meta"]:
                if nested_key in data and isinstance(data[nested_key], dict):
                    nested_usage = data[nested_key]
                    parsed = self._parse_usage_tokens(nested_usage)
                    if (
                        parsed["input_tokens"] is not None
                        or parsed["output_tokens"] is not None
                    ):
                        return {**nested_usage, **parsed}

            return None
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug(f"Failed to parse response body for usage: {e}")
            return None

    async def _calculate_and_deduct_payment(
        self, private_key: str, usage: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate cost from usage and deduct payment from the provided wallet.

        Args:
            private_key: Solana wallet private key (JSON array format or base58 string).
            usage: Usage data containing token counts.

        Returns:
            Dict with payment details including transaction signature.
        """

        # Extract token counts - usage should already be normalized by _extract_usage_from_response
        # but we'll use extract_usage_token_counts as a fallback for compatibility
        token_counts = extract_usage_token_counts(usage)

        # If usage dict already has normalized keys from our parser, use those
        if "input_tokens" in usage and isinstance(usage["input_tokens"], int):
            token_counts["input_tokens"] = usage["input_tokens"]
        if "output_tokens" in usage and isinstance(usage["output_tokens"], int):
            token_counts["output_tokens"] = usage["output_tokens"]
        if "total_tokens" in usage and isinstance(usage["total_tokens"], int):
            token_counts["total_tokens"] = usage["total_tokens"]

        # Calculate cost using the configured rates
        usd_cost = 0.0
        pricing = {
            "usd_cost": 0.0,
            "source": "middleware_rates",
            "input_tokens": token_counts["input_tokens"],
            "output_tokens": token_counts["output_tokens"],
            "total_tokens": token_counts["total_tokens"],
            "input_cost_per_million_usd": self.input_cost_per_million_usd,
            "output_cost_per_million_usd": self.output_cost_per_million_usd,
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
                * self.input_cost_per_million_usd
            )
            output_cost = (
                (token_counts["output_tokens"] or 0)
                / 1_000_000.0
                * self.output_cost_per_million_usd
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
            logger.info(
                f"Zero or negative cost calculated, skipping payment: {usd_cost}"
            )
            return {
                "status": "skipped",
                "reason": "zero_cost",
                "pricing": pricing,
            }

        # Get token price
        token_price_usd = await token_price_fetcher.get_price_usd(
            self.payment_token.value
        )

        # Calculate payment amounts
        payment_amounts = calculate_payment_amounts(
            usd_cost, token_price_usd, self.payment_token
        )

        # Parse keypair
        try:
            payer = parse_keypair_from_string(private_key)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to parse wallet private key: {str(e)}",
            )

        # Send payment (currently SOL only for automatic settlement)
        if self.payment_token != PaymentToken.SOL:
            raise HTTPException(
                status_code=400,
                detail=f"Automatic settlement currently supports SOL only. Requested: {self.payment_token.value}",
            )

        try:
            # Split payment: treasury gets fee, recipient gets the rest
            treasury_lamports = int(payment_amounts["fee_amount_units"])
            recipient_lamports = int(payment_amounts["agent_amount_units"])

            tx_sig = await send_and_confirm_split_sol_payment(
                payer=payer,
                treasury_pubkey_str=self._treasury_pubkey,
                recipient_pubkey_str=self._recipient_pubkey,
                treasury_lamports=treasury_lamports,
                recipient_lamports=recipient_lamports,
                skip_preflight=self.skip_preflight,
                commitment=self.commitment,
            )
            tx_sig = str(tx_sig).strip()

            return {
                "status": "paid",
                "transaction_signature": tx_sig,
                "pricing": pricing,
                "payment": {
                    "total_amount_lamports": payment_amounts["total_amount_units"],
                    "total_amount_sol": payment_amounts["total_amount_token"],
                    "total_amount_usd": usd_cost,
                    "treasury": {
                        "pubkey": self._treasury_pubkey,
                        "amount_lamports": treasury_lamports,
                        "amount_sol": payment_amounts["fee_amount_token"],
                        "amount_usd": usd_cost * config.SETTLEMENT_FEE_PERCENT,
                    },
                    "recipient": {
                        "pubkey": self._recipient_pubkey,
                        "amount_lamports": recipient_lamports,
                        "amount_sol": payment_amounts["agent_amount_token"],
                        "amount_usd": usd_cost * (1 - config.SETTLEMENT_FEE_PERCENT),
                    },
                },
            }
        except Exception as e:
            logger.error(f"Payment deduction failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to deduct payment: {str(e)}",
            )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request and apply settlement if applicable."""
        path = request.url.path

        # Skip if not in allowed endpoints
        if not self._should_process(path):
            return await call_next(request)

        # Extract wallet private key
        private_key = self._extract_wallet_private_key(request)
        if not private_key:
            if self.require_wallet:
                raise HTTPException(
                    status_code=401,
                    detail=f"Missing wallet private key in header: {self.wallet_private_key_header}",
                )
            # If wallet not required, skip settlement
            return await call_next(request)

        # Execute the endpoint
        response = await call_next(request)

        # Only process successful responses
        if response.status_code >= 400:
            return response

        # Extract usage from response
        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        usage = await self._extract_usage_from_response(response_body)

        if not usage:
            logger.warning(
                f"No usage data found in response for {path}. Response keys: {list(json.loads(response_body.decode('utf-8')).keys()) if response_body else 'empty'}"
            )
            # Return original response if no usage found
            return Response(
                content=response_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        # Calculate and deduct payment
        try:
            payment_result = await self._calculate_and_deduct_payment(
                private_key, usage
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Settlement error: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Settlement failed: {str(e)}",
            )

        # Modify response to include usage/payment info if requested
        if self.include_usage_in_response:
            try:
                response_data = json.loads(response_body.decode("utf-8"))
                response_data["atp_settlement"] = payment_result
                response_data["atp_usage"] = usage
                response_body = json.dumps(response_data).encode("utf-8")
            except Exception as e:
                logger.warning(f"Failed to add settlement info to response: {e}")

        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )


def create_settlement_middleware(
    allowed_endpoints: List[str],
    input_cost_per_million_usd: float,
    output_cost_per_million_usd: float,
    **kwargs: Any,
) -> type[ATPSettlementMiddleware]:
    """
    Factory function to create a configured ATP settlement middleware.

    Example:
        middleware = create_settlement_middleware(
            allowed_endpoints=["/v1/chat", "/v1/completions"],
            input_cost_per_million_usd=10.0,
            output_cost_per_million_usd=30.0,
            wallet_private_key_header="x-wallet-private-key",
            recipient_pubkey="YourPublicKeyHere",  # Optional: defaults to SWARMS_TREASURY_PUBKEY
        )
        app.add_middleware(middleware)
    """
    return type(
        "ConfiguredATPSettlementMiddleware",
        (ATPSettlementMiddleware,),
        {
            "__init__": lambda self, app: ATPSettlementMiddleware.__init__(
                self,
                app,
                allowed_endpoints=allowed_endpoints,
                input_cost_per_million_usd=input_cost_per_million_usd,
                output_cost_per_million_usd=output_cost_per_million_usd,
                **kwargs,
            )
        },
    )
