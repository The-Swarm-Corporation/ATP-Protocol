"""
FastAPI middleware for ATP settlement on any endpoint.

This middleware enables automatic payment deduction from Solana wallets
based on token usage (input/output tokens) for any configured endpoint.

The middleware delegates all settlement logic to the ATP Settlement Service,
ensuring immutable and centralized settlement operations.

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
from atp.settlement_client import SettlementServiceClient


class ATPSettlementMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware that automatically deducts payment from Solana wallets
    based on token usage for configured endpoints.

    The middleware delegates all settlement logic to the ATP Settlement Service,
    ensuring immutable and centralized settlement operations.

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
            # settlement_service_url is optional - uses ATP_SETTLEMENT_URL env var by default
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
        settlement_service_url: Optional[str] = None,
    ):
        """
        Initialize the ATP settlement middleware.

        The middleware delegates all settlement logic to the ATP Settlement Service.
        All settlement operations are handled by the immutable settlement service.

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
            settlement_service_url: Base URL of the settlement service. If not provided, uses
                ATP_SETTLEMENT_URL environment variable (default: http://localhost:8001).
                The middleware always uses the settlement service for all settlement operations.
        """
        super().__init__(app)
        self.allowed_endpoints: Set[str] = set(allowed_endpoints)
        self.input_cost_per_million_usd = input_cost_per_million_usd
        self.output_cost_per_million_usd = output_cost_per_million_usd
        self.wallet_private_key_header = (
            wallet_private_key_header.lower()
        )
        self.payment_token = payment_token
        # Recipient pubkey - configurable, the endpoint host receives the main payment
        self._recipient_pubkey = recipient_pubkey
        if not self._recipient_pubkey:
            raise ValueError("recipient_pubkey must be provided")
        # Treasury pubkey - always uses SWARMS_TREASURY_PUBKEY for processing fees
        self._treasury_pubkey = config.SWARMS_TREASURY_PUBKEY
        if not self._treasury_pubkey:
            raise ValueError(
                "SWARMS_TREASURY_PUBKEY must be set in configuration"
            )
        self.skip_preflight = skip_preflight
        self.commitment = commitment
        self.usage_response_key = usage_response_key
        self.include_usage_in_response = include_usage_in_response
        self.require_wallet = require_wallet
        # Always use settlement service - initialize client with config value or provided URL
        service_url = (
            settlement_service_url or config.ATP_SETTLEMENT_URL
        )
        self.settlement_service_client = SettlementServiceClient(
            base_url=service_url
        )

    def _should_process(self, path: str) -> bool:
        """Check if the request path should be processed by this middleware."""
        return path in self.allowed_endpoints

    def _extract_wallet_private_key(
        self, request: Request
    ) -> Optional[str]:
        """Extract wallet private key from request headers."""
        return request.headers.get(self.wallet_private_key_header)

    async def _extract_usage_from_response(
        self, response_body: bytes
    ) -> Optional[Dict[str, Any]]:
        """
        Extract usage information from response body.

        Tries multiple strategies:
        1. Look for usage data at the configured usage_response_key
        2. Check if the entire response contains usage-like keys
        3. Try nested structures (usage.usage, meta.usage, etc.)

        The usage data is then sent to the settlement service for parsing,
        so we just need to extract the raw usage object.
        """
        try:
            body_str = response_body.decode("utf-8")
            if not body_str.strip():
                return None
            data = json.loads(body_str)

            # Strategy 1: Try the configured usage key first
            usage = data.get(self.usage_response_key)
            if usage and isinstance(usage, dict):
                return usage

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
                    return data

            # Strategy 3: Try nested structures
            # Check for usage nested in common locations
            for nested_key in [
                "usage",
                "token_usage",
                "tokens",
                "statistics",
                "meta",
            ]:
                if nested_key in data and isinstance(
                    data[nested_key], dict
                ):
                    nested_usage = data[nested_key]
                    # Check if it looks like usage data
                    if any(
                        key in nested_usage
                        for key in [
                            "input_tokens",
                            "output_tokens",
                            "prompt_tokens",
                            "completion_tokens",
                            "tokens",
                        ]
                    ):
                        return nested_usage

            return None
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug(
                f"Failed to parse response body for usage: {e}"
            )
            return None

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
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

        # Calculate and deduct payment via settlement service
        try:
            payment_result = await self.settlement_service_client.settle(
                private_key=private_key,
                usage=usage,
                input_cost_per_million_usd=self.input_cost_per_million_usd,
                output_cost_per_million_usd=self.output_cost_per_million_usd,
                recipient_pubkey=self._recipient_pubkey,
                payment_token=self.payment_token.value,
                treasury_pubkey=self._treasury_pubkey,
                skip_preflight=self.skip_preflight,
                commitment=self.commitment,
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
                response_data = json.loads(
                    response_body.decode("utf-8")
                )
                response_data["atp_settlement"] = payment_result
                response_data["atp_usage"] = usage
                response_body = json.dumps(response_data).encode(
                    "utf-8"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to add settlement info to response: {e}"
                )

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
