"""
ATP Client — user-facing API for the ATP Protocol.

This module provides :class:`ATPClient`, a high-level client for:

1. **Calling the facilitator (settlement service)** — parse usage, calculate
   payment, execute settlement (pay recipient + treasury on Solana).
2. **Calling ATP-protected endpoints** — send requests with wallet auth in
   headers and automatically decrypt responses after payment is confirmed.
3. **Health checks** — verify the settlement service is reachable.

Use this client when you are a *caller* of ATP-protected APIs or when you want
to run settlement flows (e.g. pay a recipient for token usage) without going
through an HTTP endpoint.

**See also**

- :class:`atp.middleware.ATPSettlementMiddleware` — server-side FastAPI middleware
  that protects endpoints and performs settlement; use when you *host* the API.
- :class:`atp.settlement_client.SettlementServiceClient` — low-level HTTP client
  for the settlement service.
"""

from __future__ import annotations

import json
import traceback
from typing import Any, Dict, Optional, Union

import httpx

from atp.config import ATP_SETTLEMENT_URL, ATP_SETTLEMENT_TIMEOUT
from atp.encryption import ResponseEncryptor
from atp.schemas import PaymentToken
from atp.settlement_client import (
    SettlementServiceClient,
)

from loguru import logger

class ATPClient:
    """
    User-facing client for the ATP Protocol.

    Use this client to call the facilitator (settlement service) or to call
    APIs protected by :class:`atp.middleware.ATPSettlementMiddleware`. The client
    adds wallet authentication to requests and can decrypt responses that the
    middleware encrypts until payment is confirmed.

    **Capabilities**

    - **Facilitator**: :meth:`parse_usage`, :meth:`calculate_payment`, :meth:`settle`, :meth:`health_check`
    - **ATP-protected APIs**: :meth:`request`, :meth:`post`, :meth:`get` (wallet in headers, optional auto-decrypt)

    **See also:** :class:`atp.middleware.ATPSettlementMiddleware` (server-side).

    **Example Usage:**
    
        ```python
        from atp.client import ATPClient
        from atp.schemas import PaymentToken
        
        # Initialize client with wallet
        client = ATPClient(
            wallet_private_key="[1,2,3,...]",  # Your wallet private key
            settlement_service_url="https://facilitator.swarms.world"
        )
        
        # Call facilitator directly
        usage = {"input_tokens": 1000, "output_tokens": 500}
        payment = await client.calculate_payment(
            usage=usage,
            input_cost_per_million_usd=10.0,
            output_cost_per_million_usd=30.0,
            payment_token=PaymentToken.SOL
        )
        
        # Execute settlement
        result = await client.settle(
            usage=usage,
            input_cost_per_million_usd=10.0,
            output_cost_per_million_usd=30.0,
            recipient_pubkey="RecipientPublicKeyHere",
            payment_token=PaymentToken.SOL
        )
        
        # Make request to ATP-protected endpoint
        response = await client.request(
            method="POST",
            url="https://api.example.com/v1/chat",
            json={"message": "Hello!"}
        )
        # Wallet is automatically included in headers
        # Response is automatically decrypted if encrypted
        ```
    
    **Attributes:**
        wallet_private_key (str): Wallet private key for authentication and payments.
        settlement_service_url (str): Base URL of the settlement service.
        settlement_timeout (float): Timeout for settlement operations in seconds.
        wallet_private_key_header (str): HTTP header name for wallet key (default: "x-wallet-private-key").
        settlement_client (SettlementServiceClient): Internal client for settlement service.
        encryptor (ResponseEncryptor): Encryptor for handling encrypted responses.
    """

    def __init__(
        self,
        wallet_private_key: Optional[str] = None,
        settlement_service_url: Optional[str] = ATP_SETTLEMENT_URL,
        settlement_timeout: Optional[float] = None,
        wallet_private_key_header: str = "x-wallet-private-key",
        verbose: bool = False,
    ):
        """
        Initialize the ATP client.
        
        Args:
            wallet_private_key: Wallet private key for authentication and payments.
                Can be in JSON array format (e.g., "[1,2,3,...]") or base58 string.
                If not provided, must be passed per-request.
            settlement_service_url: Base URL of the settlement service.
                Default: from ATP_SETTLEMENT_URL env var or "https://facilitator.swarms.world".
            settlement_timeout: Timeout for settlement operations in seconds.
                Default: from ATP_SETTLEMENT_TIMEOUT env var or 300.0 (5 minutes).
            wallet_private_key_header: HTTP header name for wallet private key.
                Default: "x-wallet-private-key".
            verbose: If True, enables detailed logging with tracebacks for debugging.
                Default: False.
        """
        self.wallet_private_key = wallet_private_key
        self.wallet_private_key_header = wallet_private_key_header
        self.settlement_service_url = (
            settlement_service_url or ATP_SETTLEMENT_URL
        )
        self.settlement_timeout = (
            settlement_timeout if settlement_timeout is not None else ATP_SETTLEMENT_TIMEOUT
        )
        self.verbose = verbose
        
        # Initialize settlement service client
        self.settlement_client = SettlementServiceClient(
            base_url=self.settlement_service_url,
            timeout=self.settlement_timeout,
        )
        
        # Initialize encryptor for handling encrypted responses
        self.encryptor = ResponseEncryptor()
        
        if self.verbose:
            logger.info(f"ATPClient initialized with settlement_service_url={self.settlement_service_url}, timeout={self.settlement_timeout}")

    def _get_headers(
        self, wallet_private_key: Optional[str] = None, **kwargs
    ) -> Dict[str, str]:
        """
        Get HTTP headers with wallet authentication.
        
        Args:
            wallet_private_key: Wallet private key to use. If not provided,
                uses the client's default wallet_private_key.
            **kwargs: Additional headers to include.
            
        Returns:
            Dict of HTTP headers.
        """
        headers = {"Content-Type": "application/json", **kwargs}
        
        # Add wallet private key if available
        key = wallet_private_key or self.wallet_private_key
        if key:
            headers[self.wallet_private_key_header] = key
        
        return headers

    async def parse_usage(
        self, usage_data: Dict[str, Any]
    ) -> Dict[str, Optional[int]]:
        """
        Parse usage tokens from various API formats.
        
        This method uses the facilitator to parse usage data from any supported
        format (OpenAI, Anthropic, Google, etc.) and normalize it to a standard format.
        
        Args:
            usage_data: Usage data in any supported format. Can be the entire
                response body or just the usage portion.
                
        Returns:
            Dict with normalized keys:
                - `input_tokens` (Optional[int]): Number of input/prompt tokens
                - `output_tokens` (Optional[int]): Number of output/completion tokens
                - `total_tokens` (Optional[int]): Total number of tokens
                
        Raises:
            SettlementServiceError: If the facilitator returns an error.
            
        Example:
            ```python
            usage = await client.parse_usage({
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150
            })
            # Returns: {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
            ```
        """
        if self.verbose:
            logger.debug(f"Parsing usage data: {usage_data}")
        
        try:
            result = await self.settlement_client.parse_usage(usage_data)
            if self.verbose:
                logger.info(f"Successfully parsed usage: {result}")
            return result
        except Exception as e:
            if self.verbose:
                logger.error(f"Error parsing usage data: {e}\n{traceback.format_exc()}")
            else:
                logger.error(f"Error parsing usage data: {e}")
            raise

    async def calculate_payment(
        self,
        usage: Dict[str, Any],
        input_cost_per_million_usd: float,
        output_cost_per_million_usd: float,
        payment_token: Union[PaymentToken, str] = PaymentToken.SOL,
    ) -> Dict[str, Any]:
        """
        Calculate payment amounts from usage data.
        
        This method uses the facilitator to calculate payment amounts based on
        token usage and pricing rates. It does not execute any payment.
        
        Args:
            usage: Usage data containing token counts. Supports same formats as
                `parse_usage` method.
            input_cost_per_million_usd: Cost per million input tokens in USD.
            output_cost_per_million_usd: Cost per million output tokens in USD.
            payment_token: Token to use for payment. Must be "SOL" or "USDC".
                Default: PaymentToken.SOL.
                
        Returns:
            Dict with payment calculation details:
                - `status` (str): "calculated" or "skipped" (if zero cost)
                - `pricing` (dict): Pricing information with token counts and costs
                - `payment_amounts` (dict, optional): Payment amounts in token units
                - `token_price_usd` (float, optional): Current token price in USD
                
        Raises:
            SettlementServiceError: If the facilitator returns an error.
            
        Example:
            ```python
            result = await client.calculate_payment(
                usage={"input_tokens": 1000, "output_tokens": 500},
                input_cost_per_million_usd=10.0,
                output_cost_per_million_usd=30.0,
                payment_token=PaymentToken.SOL
            )
            ```
        """
        payment_token_str = (
            payment_token.value if isinstance(payment_token, PaymentToken) else payment_token
        )
        
        if self.verbose:
            logger.debug(
                f"Calculating payment: usage={usage}, "
                f"input_cost_per_million_usd={input_cost_per_million_usd}, "
                f"output_cost_per_million_usd={output_cost_per_million_usd}, "
                f"payment_token={payment_token_str}"
            )
        
        try:
            result = await self.settlement_client.calculate_payment(
                usage=usage,
                input_cost_per_million_usd=input_cost_per_million_usd,
                output_cost_per_million_usd=output_cost_per_million_usd,
                payment_token=payment_token_str,
            )
            if self.verbose:
                logger.info(f"Payment calculation successful: {result}")
            return result
        except Exception as e:
            if self.verbose:
                logger.error(f"Error calculating payment: {e}\n{traceback.format_exc()}")
            else:
                logger.error(f"Error calculating payment: {e}")
            raise

    async def settle(
        self,
        usage: Dict[str, Any],
        input_cost_per_million_usd: float,
        output_cost_per_million_usd: float,
        recipient_pubkey: str,
        payment_token: Union[PaymentToken, str] = PaymentToken.SOL,
        skip_preflight: bool = False,
        commitment: str = "confirmed",
        wallet_private_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a settlement payment on Solana blockchain.
        
        This method uses the facilitator to execute a complete settlement:
        parse usage, calculate payment, fetch token prices, create and sign
        transaction, send to Solana, and wait for confirmation.
        
        Args:
            usage: Usage data containing token counts. Supports same formats as
                `parse_usage` method.
            input_cost_per_million_usd: Cost per million input tokens in USD.
            output_cost_per_million_usd: Cost per million output tokens in USD.
            recipient_pubkey: Solana public key of the recipient wallet (base58 encoded).
                This wallet receives the net payment after fees.
            payment_token: Token to use for payment. Currently only "SOL" is supported
                for automatic settlement. Default: PaymentToken.SOL.
            skip_preflight: Whether to skip preflight simulation. Default: False.
            commitment: Solana commitment level for transaction confirmation:
                - "processed": Fastest, but may be rolled back
                - "confirmed": Recommended default, confirmed by cluster
                - "finalized": Slowest, but cannot be rolled back
                Default: "confirmed".
            wallet_private_key: Wallet private key to use for payment. If not provided,
                uses the client's default wallet_private_key.
                
        Returns:
            Dict with payment details:
                - `status` (str): "paid" if successful, "skipped" if zero cost
                - `transaction_signature` (str, optional): Solana transaction signature
                - `pricing` (dict): Complete cost breakdown
                - `payment` (dict, optional): Payment details including amounts and splits
                
        Raises:
            SettlementServiceError: If the facilitator returns an error.
            ValueError: If wallet_private_key is not provided.
            
        Example:
            ```python
            result = await client.settle(
                usage={"input_tokens": 1000, "output_tokens": 500},
                input_cost_per_million_usd=10.0,
                output_cost_per_million_usd=30.0,
                recipient_pubkey="RecipientPublicKeyHere",
                payment_token=PaymentToken.SOL
            )
            ```
        """
        private_key = wallet_private_key or self.wallet_private_key
        if not private_key:
            error_msg = (
                "wallet_private_key must be provided either in client initialization "
                "or as a parameter to this method"
            )
            if self.verbose:
                logger.error(f"{error_msg}\n{traceback.format_exc()}")
            else:
                logger.error(error_msg)
            raise ValueError(error_msg)
        
        payment_token_str = (
            payment_token.value if isinstance(payment_token, PaymentToken) else payment_token
        )
        
        if self.verbose:
            logger.debug(
                f"Settling payment: usage={usage}, "
                f"input_cost_per_million_usd={input_cost_per_million_usd}, "
                f"output_cost_per_million_usd={output_cost_per_million_usd}, "
                f"recipient_pubkey={recipient_pubkey}, "
                f"payment_token={payment_token_str}, "
                f"skip_preflight={skip_preflight}, "
                f"commitment={commitment}"
            )
        
        try:
            result = await self.settlement_client.settle(
                private_key=private_key,
                usage=usage,
                input_cost_per_million_usd=input_cost_per_million_usd,
                output_cost_per_million_usd=output_cost_per_million_usd,
                recipient_pubkey=recipient_pubkey,
                payment_token=payment_token_str,
                skip_preflight=skip_preflight,
                commitment=commitment,
            )
            if self.verbose:
                logger.info(f"Settlement successful: {result}")
            return result
        except Exception as e:
            if self.verbose:
                logger.error(f"Error during settlement: {e}\n{traceback.format_exc()}")
            else:
                logger.error(f"Error during settlement: {e}")
            raise

    async def health_check(self) -> Dict[str, Any]:
        """
        Check if the facilitator (settlement service) is healthy.
        
        Returns:
            Dict with health status information, typically including:
                - `status` (str): Service status (e.g., "healthy")
                - `service` (str): Service name
                - `version` (str): Service version
                
        Raises:
            SettlementServiceError: If the facilitator is unreachable or returns an error.
            
        Example:
            ```python
            health = await client.health_check()
            print(f"Service status: {health['status']}")
            ```
        """
        if self.verbose:
            logger.debug("Checking settlement service health")
        
        try:
            result = await self.settlement_client.health_check()
            if self.verbose:
                logger.info(f"Health check successful: {result}")
            return result
        except Exception as e:
            if self.verbose:
                logger.error(f"Error during health check: {e}\n{traceback.format_exc()}")
            else:
                logger.error(f"Error during health check: {e}")
            raise

    async def request(
        self,
        method: str,
        url: str,
        wallet_private_key: Optional[str] = None,
        auto_decrypt: bool = True,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to an ATP-protected endpoint.
        
        This method automatically:
        - Adds wallet authentication headers
        - Handles encrypted responses from ATP middleware
        - Decrypts response data if encrypted
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.).
            url: Full URL of the endpoint.
            wallet_private_key: Wallet private key to use. If not provided,
                uses the client's default wallet_private_key.
            auto_decrypt: Whether to automatically decrypt encrypted responses.
                Default: True.
            **kwargs: Additional arguments to pass to httpx (e.g., json, data, params, etc.).
                
        Returns:
            Dict containing the response data. If the response was encrypted,
            it will be automatically decrypted if auto_decrypt=True.
            
        Raises:
            httpx.HTTPError: If the HTTP request fails.
            ValueError: If wallet_private_key is required but not provided.
            
        Example:
            ```python
            # Make a POST request to an ATP-protected endpoint
            response = await client.request(
                method="POST",
                url="https://api.example.com/v1/chat",
                json={"message": "Hello!"}
            )
            # Response is automatically decrypted if encrypted
            print(response["output"])  # Agent output
            print(response["atp_settlement"])  # Payment details
            ```
        """
        if self.verbose:
            logger.debug(f"Making {method} request to {url}")
        
        try:
            # Check if wallet key is available
            key = wallet_private_key or self.wallet_private_key
            if not key:
                raise ValueError(
                    "wallet_private_key is required for ATP-protected endpoints. "
                    "Provide it in client initialization or pass it to the request method. "
                    "Example: client = ATPClient(wallet_private_key='[1,2,3,...]')"
                )
            
            # Get headers with wallet authentication
            headers = self._get_headers(wallet_private_key=wallet_private_key)
            
            # Merge with any headers provided in kwargs
            if "headers" in kwargs:
                headers.update(kwargs.pop("headers"))
            
            if self.verbose:
                logger.debug(f"Request headers: {list(headers.keys())}")
            
            # Make the request
            async with httpx.AsyncClient(timeout=self.settlement_timeout) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    **kwargs,
                )
                response.raise_for_status()
                
                if self.verbose:
                    logger.debug(f"Response status: {response.status_code}")
                
                # Parse JSON response
                try:
                    response_data = response.json()
                except json.JSONDecodeError as e:
                    if self.verbose:
                        logger.warning(f"Response is not JSON, returning as text: {e}")
                    # If not JSON, return text
                    return {"text": response.text}
                
                # Auto-decrypt if enabled and response appears encrypted
                if auto_decrypt:
                    if self.verbose:
                        logger.debug("Attempting to decrypt response")
                    response_data = self.encryptor.decrypt_response_data(
                        response_data
                    )
                
                if self.verbose:
                    logger.info(f"Request successful: {method} {url}")
                
                return response_data
        except httpx.HTTPError as e:
            if self.verbose:
                logger.error(f"HTTP error during request {method} {url}: {e}\n{traceback.format_exc()}")
            else:
                logger.error(f"HTTP error during request {method} {url}: {e}")
            raise
        except Exception as e:
            if self.verbose:
                logger.error(f"Error during request {method} {url}: {e}\n{traceback.format_exc()}")
            else:
                logger.error(f"Error during request {method} {url}: {e}")
            raise

    async def post(
        self,
        url: str,
        wallet_private_key: Optional[str] = None,
        auto_decrypt: bool = True,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Make a POST request to an ATP-protected endpoint.
        
        Convenience method for POST requests. See `request` method for details.
        
        Args:
            url: Full URL of the endpoint.
            wallet_private_key: Wallet private key to use. If not provided,
                uses the client's default wallet_private_key.
            auto_decrypt: Whether to automatically decrypt encrypted responses.
                Default: True.
            **kwargs: Additional arguments to pass to httpx (e.g., json, data, params, etc.).
                
        Returns:
            Dict containing the response data.
            
        Example:
            ```python
            response = await client.post(
                url="https://api.example.com/v1/chat",
                json={"message": "Hello!"}
            )
            ```
        """
        try:
            return await self.request(
                method="POST",
                url=url,
                wallet_private_key=wallet_private_key,
                auto_decrypt=auto_decrypt,
                **kwargs,
            )
        except Exception as e:
            if self.verbose:
                logger.error(f"Error in POST request to {url}: {e}\n{traceback.format_exc()}")
            else:
                logger.error(f"Error in POST request to {url}: {e}")
            raise

    async def get(
        self,
        url: str,
        wallet_private_key: Optional[str] = None,
        auto_decrypt: bool = True,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Make a GET request to an ATP-protected endpoint.
        
        Convenience method for GET requests. See `request` method for details.
        
        Args:
            url: Full URL of the endpoint.
            wallet_private_key: Wallet private key to use. If not provided,
                uses the client's default wallet_private_key.
            auto_decrypt: Whether to automatically decrypt encrypted responses.
                Default: True.
            **kwargs: Additional arguments to pass to httpx (e.g., params, headers, etc.).
                
        Returns:
            Dict containing the response data.
            
        Example:
            ```python
            response = await client.get(
                url="https://api.example.com/v1/status",
                params={"id": "123"}
            )
            ```
        """
        try:
            return await self.request(
                method="GET",
                url=url,
                wallet_private_key=wallet_private_key,
                auto_decrypt=auto_decrypt,
                **kwargs,
            )
        except Exception as e:
            if self.verbose:
                logger.error(f"Error in GET request to {url}: {e}\n{traceback.format_exc()}")
            else:
                logger.error(f"Error in GET request to {url}: {e}")
            raise
