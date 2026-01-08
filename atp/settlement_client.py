"""
Client for calling the ATP Settlement Service.

This module provides a client interface for communicating with the
settlement service API, allowing the middleware to delegate settlement
logic to the immutable service.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx
from loguru import logger

from atp.config import ATP_SETTLEMENT_URL


class SettlementServiceClient:
    """Client for ATP Settlement Service API."""

    def __init__(
        self,
        base_url: str = ATP_SETTLEMENT_URL,
        timeout: float = 30.0,
    ):
        """
        Initialize the settlement service client.

        Args:
            base_url: Base URL of the settlement service (default: ATP_SETTLEMENT_URL).
            timeout: Request timeout in seconds (default: 30.0).
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def parse_usage(
        self, usage_data: Dict[str, Any]
    ) -> Dict[str, Optional[int]]:
        """
        Parse usage tokens from various API formats.

        Args:
            usage_data: Usage data in any supported format.

        Returns:
            Dict with normalized keys: input_tokens, output_tokens, total_tokens
        """
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                response = await client.post(
                    f"{self.base_url}/v1/settlement/parse-usage",
                    json={"usage_data": usage_data},
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            logger.error(
                f"Failed to parse usage via settlement service: {e}"
            )
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error calling settlement service: {e}"
            )
            raise

    async def calculate_payment(
        self,
        usage: Dict[str, Any],
        input_cost_per_million_usd: float,
        output_cost_per_million_usd: float,
        payment_token: str = "SOL",
    ) -> Dict[str, Any]:
        """
        Calculate payment amounts from usage data.

        Args:
            usage: Usage data containing token counts.
            input_cost_per_million_usd: Cost per million input tokens in USD.
            output_cost_per_million_usd: Cost per million output tokens in USD.
            payment_token: Token to use for payment (SOL or USDC).

        Returns:
            Dict with payment calculation details.
        """
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                response = await client.post(
                    f"{self.base_url}/v1/settlement/calculate-payment",
                    json={
                        "usage": usage,
                        "input_cost_per_million_usd": input_cost_per_million_usd,
                        "output_cost_per_million_usd": output_cost_per_million_usd,
                        "payment_token": payment_token,
                    },
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            logger.error(
                f"Failed to calculate payment via settlement service: {e}"
            )
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error calling settlement service: {e}"
            )
            raise

    async def settle(
        self,
        private_key: str,
        usage: Dict[str, Any],
        input_cost_per_million_usd: float,
        output_cost_per_million_usd: float,
        recipient_pubkey: str,
        payment_token: str = "SOL",
        treasury_pubkey: Optional[str] = None,
        skip_preflight: bool = False,
        commitment: str = "confirmed",
    ) -> Dict[str, Any]:
        """
        Execute a settlement payment.

        Args:
            private_key: Solana wallet private key.
            usage: Usage data containing token counts.
            input_cost_per_million_usd: Cost per million input tokens in USD.
            output_cost_per_million_usd: Cost per million output tokens in USD.
            recipient_pubkey: Solana public key of the recipient wallet.
            payment_token: Token to use for payment (SOL or USDC).
            treasury_pubkey: Treasury pubkey for processing fee (optional).
            skip_preflight: Whether to skip preflight simulation.
            commitment: Solana commitment level.

        Returns:
            Dict with payment details including transaction signature.
        """
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                payload: Dict[str, Any] = {
                    "private_key": private_key,
                    "usage": usage,
                    "input_cost_per_million_usd": input_cost_per_million_usd,
                    "output_cost_per_million_usd": output_cost_per_million_usd,
                    "recipient_pubkey": recipient_pubkey,
                    "payment_token": payment_token,
                    "skip_preflight": skip_preflight,
                    "commitment": commitment,
                }
                if treasury_pubkey:
                    payload["treasury_pubkey"] = treasury_pubkey

                response = await client.post(
                    f"{self.base_url}/v1/settlement/settle",
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            logger.error(
                f"Failed to settle payment via settlement service: {e}"
            )
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error calling settlement service: {e}"
            )
            raise

    async def health_check(self) -> Dict[str, Any]:
        """
        Check if the settlement service is healthy.

        Returns:
            Dict with health status.
        """
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                response = await client.get(f"{self.base_url}/health")
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Health check failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during health check: {e}")
            raise
