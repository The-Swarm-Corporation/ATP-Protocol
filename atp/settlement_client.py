"""
Client for calling the ATP Settlement Service.

This module provides a client interface for communicating with the
settlement service API, allowing the middleware to delegate settlement
logic to the immutable service.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx
from loguru import logger

from atp.config import ATP_SETTLEMENT_URL, ATP_SETTLEMENT_TIMEOUT


class SettlementServiceError(Exception):
    """
    Exception raised when settlement service returns an error.
    
    This exception carries detailed error information from the settlement service
    response, including HTTP status codes, error types, and detailed error messages.
    It provides structured error information that can be easily converted to API
    response formats.
    
    **Attributes:**
        status_code (Optional[int]): HTTP status code from the settlement service response.
        error_detail (Optional[str]): Detailed error message from the service.
        error_type (Optional[str]): Type/category of the error (e.g., "Client error",
            "Server error", "Timeout", "Connection error").
        response_body (Optional[Dict[str, Any]]): Full response body if available.
    
    **Error Types:**
        - "Invalid request" (400): Bad request format or missing required parameters
        - "Authentication error" (401): Authentication failed
        - "Authorization error" (403): Insufficient permissions
        - "Not found" (404): Resource not found
        - "Client error" (4xx): Other client-side errors
        - "Server error" (5xx): Server-side errors
        - "Timeout": Request timed out (payment may have succeeded)
        - "Connection timeout": Connection to service timed out
        - "Connection error": Failed to connect to service
    
    **Example:**
        ```python
        try:
            result = await client.settle(...)
        except SettlementServiceError as e:
            print(f"Error type: {e.error_type}")
            print(f"Status code: {e.status_code}")
            print(f"Detail: {e.error_detail}")
            # Convert to dict for API response
            error_dict = e.to_dict()
        ```
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        error_detail: Optional[str] = None,
        error_type: Optional[str] = None,
        response_body: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize settlement service error.

        Args:
            message: Error message.
            status_code: HTTP status code from the response.
            error_detail: Detailed error message from the service.
            error_type: Type/category of the error.
            response_body: Full response body if available.
        """
        super().__init__(message)
        self.status_code = status_code
        self.error_detail = error_detail
        self.error_type = error_type
        self.response_body = response_body

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert error to dictionary for API responses.
        
        Returns a dictionary representation of the error suitable for including
        in API responses. The dictionary includes error type, message, detail,
        and status code.
        
        Returns:
            Dict with keys: "error" (error type), "message" (error message),
                "detail" (detailed error message, if available),
                "status_code" (HTTP status code, if available).
        """
        result: Dict[str, Any] = {
            "error": self.error_type or "Settlement service error",
            "message": str(self),
        }
        if self.error_detail:
            result["detail"] = self.error_detail
        if self.status_code:
            result["status_code"] = self.status_code
        return result


class SettlementServiceClient:
    """
    Client for ATP Settlement Service API.
    
    This client provides an interface for communicating with the ATP Settlement Service,
    which handles all settlement logic in an immutable, centralized manner. The client
    abstracts HTTP communication and provides structured error handling.
    
    **Architecture:**
    
    The settlement service is a centralized API that handles:
    - Usage token parsing from various API formats (OpenAI, Anthropic, Google, etc.)
    - Payment amount calculation based on token usage and pricing rates
    - Solana blockchain transaction execution
    - Payment verification and confirmation
    
    All settlement logic is immutable and centralized, ensuring consistency across
    all services using the ATP Protocol.
    
    **Error Handling:**
    
    The client provides comprehensive error handling:
    - Automatic extraction of error details from various response formats
    - Structured error types based on HTTP status codes
    - Special handling for timeout errors (payment may have succeeded)
    - Detailed logging with appropriate log levels
    
    **Timeout Considerations:**
    
    Settlement operations may take time due to blockchain confirmation. The default
    timeout is 300 seconds (5 minutes), but this can be configured. If a timeout occurs,
    the payment may have been sent successfully - check the blockchain for transaction
    confirmation.
    
    **Attributes:**
        base_url (str): Base URL of the settlement service (trailing slashes removed).
        timeout (float): Request timeout in seconds for all API calls.
    
    **Example Usage:**
    
        ```python
        from atp.settlement_client import SettlementServiceClient
        
        # Initialize client
        client = SettlementServiceClient(
            base_url="https://facilitator.swarms.world",
            timeout=300.0  # 5 minutes
        )
        
        # Parse usage from any format
        usage_data = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150
        }
        parsed = await client.parse_usage(usage_data)
        # Returns: {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
        
        # Calculate payment
        payment_calc = await client.calculate_payment(
            usage=usage_data,
            input_cost_per_million_usd=10.0,
            output_cost_per_million_usd=30.0,
            payment_token="SOL"
        )
        
        # Execute settlement
        result = await client.settle(
            private_key="[1,2,3,...]",  # Wallet private key
            usage=usage_data,
            input_cost_per_million_usd=10.0,
            output_cost_per_million_usd=30.0,
            recipient_pubkey="RecipientPublicKeyHere",
            payment_token="SOL"
        )
        # Returns: {"status": "paid", "transaction_signature": "...", ...}
        
        # Health check
        health = await client.health_check()
        ```
    
    **API Endpoints:**
    
    The client communicates with the following settlement service endpoints:
    - `POST /v1/settlement/parse-usage`: Parse usage tokens from various formats
    - `POST /v1/settlement/calculate-payment`: Calculate payment amounts
    - `POST /v1/settlement/settle`: Execute payment transaction
    - `GET /health`: Health check endpoint
    """

    def __init__(
        self,
        base_url: str = ATP_SETTLEMENT_URL,
        timeout: Optional[float] = None,
    ):
        """
        Initialize the settlement service client.

        Args:
            base_url: Base URL of the settlement service (default: ATP_SETTLEMENT_URL).
            timeout: Request timeout in seconds (default: ATP_SETTLEMENT_TIMEOUT or 300.0).
                Settlement operations may take longer due to blockchain confirmation times.
                User-configurable - can be set via environment variable or passed directly.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout if timeout is not None else ATP_SETTLEMENT_TIMEOUT

    def _extract_error_details(
        self, response: httpx.Response
    ) -> Dict[str, Any]:
        """
        Extract error details from HTTP response.

        This internal method parses error information from various response formats
        commonly used by FastAPI and other web frameworks. It handles JSON responses,
        text responses, and multiple error field formats.

        **Supported Error Formats:**
            - FastAPI: `{"detail": "error message"}`
            - Generic: `{"error": "error message", "type": "error_type"}`
            - Message: `{"message": "error message"}`
            - Plain text: Non-JSON text responses

        Args:
            response: HTTP response object from httpx.

        Returns:
            Dict with error details:
                - `status_code` (int): HTTP status code
                - `error_detail` (Optional[str]): Detailed error message
                - `error_type` (Optional[str]): Type/category of error
                - `response_body` (Optional[Dict[str, Any]]): Full parsed response body
        """
        error_info: Dict[str, Any] = {
            "status_code": response.status_code,
            "error_detail": None,
            "error_type": None,
            "response_body": None,
        }

        try:
            # Try to parse JSON response
            response_body = response.json()
            error_info["response_body"] = response_body

            # Extract error details from common response formats
            if isinstance(response_body, dict):
                # FastAPI error format: {"detail": "error message"}
                if "detail" in response_body:
                    error_info["error_detail"] = response_body["detail"]
                # Alternative format: {"error": "error message"}
                elif "error" in response_body:
                    error_info["error_detail"] = response_body["error"]
                    error_info["error_type"] = response_body.get("type")
                # Message field
                elif "message" in response_body:
                    error_info["error_detail"] = response_body["message"]
                    error_info["error_type"] = response_body.get("error")

        except (json.JSONDecodeError, ValueError):
            # If JSON parsing fails, use text response
            try:
                text_response = response.text
                if text_response:
                    error_info["error_detail"] = text_response
            except Exception:
                pass

        return error_info

    def _handle_http_error(
        self, error: httpx.HTTPError, operation: str
    ) -> SettlementServiceError:
        """
        Handle HTTP error and extract error details.

        This internal method processes HTTP errors from httpx and converts them into
        structured SettlementServiceError exceptions. It handles both HTTP status
        errors (with response) and network/timeout errors (without response).

        **Error Type Detection:**
            - 400: "Invalid request"
            - 401: "Authentication error"
            - 403: "Authorization error"
            - 404: "Not found"
            - 4xx: "Client error"
            - 5xx: "Server error"
            - ReadTimeout: "Timeout" (with special message about payment possibly succeeding)
            - ConnectTimeout: "Connection timeout"
            - ConnectError: "Connection error"

        **Logging:**
            - Server errors (5xx): Logged at ERROR level
            - Client errors (4xx): Logged at WARNING level
            - Network errors: Logged at ERROR level

        Args:
            error: HTTP error exception from httpx (HTTPStatusError, ReadTimeout, etc.).
            operation: Name of the operation that failed (e.g., "parse_usage", "settle")
                for logging and error messages.

        Returns:
            SettlementServiceError with extracted details including status code,
            error type, error detail, and response body (if available).

        **Note:**
            For timeout errors, the error message includes a note that the payment
            may have been sent successfully, and users should check the blockchain
            for transaction confirmation.
        """
        # Check if error has a response (HTTPStatusError)
        if hasattr(error, "response") and error.response is not None:
            response = error.response
            error_info = self._extract_error_details(response)

            # Determine error type based on status code
            status_code = error_info["status_code"]
            if 400 <= status_code < 500:
                error_type = "Client error"
                if status_code == 400:
                    error_type = "Invalid request"
                elif status_code == 401:
                    error_type = "Authentication error"
                elif status_code == 403:
                    error_type = "Authorization error"
                elif status_code == 404:
                    error_type = "Not found"
            elif status_code >= 500:
                error_type = "Server error"
            else:
                error_type = "HTTP error"

            # Build error message
            error_detail = error_info["error_detail"] or str(error)
            message = (
                f"Settlement service {operation} failed: {error_detail}"
            )

            # Log with appropriate level
            if status_code >= 500:
                logger.error(
                    f"Settlement service {operation} failed (HTTP {status_code}): {error_detail}"
                )
            else:
                logger.warning(
                    f"Settlement service {operation} failed (HTTP {status_code}): {error_detail}"
                )

            return SettlementServiceError(
                message=message,
                status_code=status_code,
                error_detail=error_detail,
                error_type=error_type,
                response_body=error_info["response_body"],
            )
        else:
            # Network/timeout errors without response
            error_type = type(error).__name__
            message = f"Settlement service {operation} failed: {str(error)}"

            # Provide more informative error messages for timeouts
            if isinstance(error, httpx.ReadTimeout):
                message = (
                    f"Settlement service {operation} timed out after {self.timeout}s. "
                    "The payment may have been sent successfully, but the settlement service "
                    "did not respond in time. Check the blockchain for transaction confirmation."
                )
                error_type = "Timeout"
            elif isinstance(error, httpx.ConnectTimeout):
                message = (
                    f"Connection to settlement service timed out during {operation}. "
                    "The service may be unreachable or overloaded."
                )
                error_type = "Connection timeout"
            elif isinstance(error, httpx.ConnectError):
                message = (
                    f"Failed to connect to settlement service during {operation}. "
                    "The service may be down or unreachable."
                )
                error_type = "Connection error"

            logger.error(f"Settlement service {operation} failed: {message}")
            return SettlementServiceError(
                message=message,
                error_type=error_type,
            )

    async def parse_usage(
        self, usage_data: Dict[str, Any]
    ) -> Dict[str, Optional[int]]:
        """
        Parse usage tokens from various API formats.

        This method sends usage data to the settlement service's parse-usage endpoint,
        which automatically detects the format and extracts token counts. Supports
        multiple API provider formats including OpenAI, Anthropic, Google/Gemini,
        Cohere, and nested structures.

        **Supported Formats:**
            - OpenAI: `prompt_tokens`, `completion_tokens`, `total_tokens`
            - Anthropic: `input_tokens`, `output_tokens`, `total_tokens`
            - Google/Gemini: `promptTokenCount`, `candidatesTokenCount`, `totalTokenCount`
            - Cohere: `tokens`, `input_tokens`, `output_tokens`
            - Nested: `usage.usage`, `meta.usage`, `statistics`

        **Args:**
            usage_data: Usage data in any supported format. Can be the entire response
                body or just the usage portion. The service handles nested structures
                automatically.

        **Returns:**
            Dict with normalized keys:
                - `input_tokens` (Optional[int]): Number of input/prompt tokens
                - `output_tokens` (Optional[int]): Number of output/completion tokens
                - `total_tokens` (Optional[int]): Total number of tokens

        **Raises:**
            SettlementServiceError: If the settlement service returns an error or
                cannot parse the usage data.

        **Example:**
            ```python
            # OpenAI format
            usage = await client.parse_usage({
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150
            })
            # Returns: {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
            
            # Nested format
            usage = await client.parse_usage({
                "response": "...",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50
                }
            })
            # Returns: {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
            ```
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
            raise self._handle_http_error(e, "parse_usage")
        except Exception as e:
            logger.error(
                f"Unexpected error calling settlement service parse_usage: {e}",
                exc_info=True,
            )
            raise SettlementServiceError(
                message=f"Unexpected error during parse_usage: {str(e)}",
                error_type="Unexpected error",
            )

    async def calculate_payment(
        self,
        usage: Dict[str, Any],
        input_cost_per_million_usd: float,
        output_cost_per_million_usd: float,
        payment_token: str = "SOL",
    ) -> Dict[str, Any]:
        """
        Calculate payment amounts from usage data.

        This method calculates payment amounts based on token usage and pricing rates.
        It parses usage tokens, calculates USD costs, fetches current token prices,
        and computes payment amounts in the specified token (SOL or USDC).

        **Calculation Process:**
            1. Parses usage tokens from the provided usage data
            2. Calculates USD cost: (input_tokens / 1M) * input_rate + (output_tokens / 1M) * output_rate
            3. Fetches current token price from price oracle
            4. Converts USD cost to token amount
            5. Calculates split: treasury fee (5% default) and agent amount (95% default)

        **Args:**
            usage: Usage data containing token counts. Supports same formats as
                `parse_usage` method. Can be raw usage data or already parsed.
            input_cost_per_million_usd: Cost per million input tokens in USD.
            output_cost_per_million_usd: Cost per million output tokens in USD.
            payment_token: Token to use for payment. Must be "SOL" or "USDC".
                Default: "SOL".

        **Returns:**
            Dict with payment calculation details:
                - `status` (str): "calculated" or "skipped" (if zero cost)
                - `pricing` (dict): Pricing information with token counts and costs
                - `payment_amounts` (dict, optional): Payment amounts in token units
                - `token_price_usd` (float, optional): Current token price in USD

        **Raises:**
            SettlementServiceError: If the settlement service returns an error.

        **Example:**
            ```python
            result = await client.calculate_payment(
                usage={"input_tokens": 1000, "output_tokens": 500},
                input_cost_per_million_usd=10.0,
                output_cost_per_million_usd=30.0,
                payment_token="SOL"
            )
            # Returns:
            # {
            #     "status": "calculated",
            #     "pricing": {
            #         "usd_cost": 0.025,  # $0.01 input + $0.015 output
            #         "input_tokens": 1000,
            #         "output_tokens": 500,
            #         ...
            #     },
            #     "payment_amounts": {
            #         "total_amount_token": 0.00125,  # SOL amount
            #         "fee_amount_token": 0.0000625,  # Treasury fee
            #         "agent_amount_token": 0.0011875,  # Agent payment
            #         ...
            #     },
            #     "token_price_usd": 20.0  # SOL price
            # }
            ```
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
            raise self._handle_http_error(e, "calculate_payment")
        except Exception as e:
            logger.error(
                f"Unexpected error calling settlement service calculate_payment: {e}",
                exc_info=True,
            )
            raise SettlementServiceError(
                message=f"Unexpected error during calculate_payment: {str(e)}",
                error_type="Unexpected error",
            )

    async def settle(
        self,
        private_key: str,
        usage: Dict[str, Any],
        input_cost_per_million_usd: float,
        output_cost_per_million_usd: float,
        recipient_pubkey: str,
        payment_token: str = "SOL",
        skip_preflight: bool = False,
        commitment: str = "confirmed",
    ) -> Dict[str, Any]:
        """
        Execute a settlement payment on Solana blockchain.

        This method performs a complete settlement flow: parses usage tokens, calculates
        payment amounts, fetches token prices, creates and signs a split payment transaction
        on Solana, sends the transaction, and waits for confirmation.

        **Settlement Flow:**
            1. Parses usage tokens from the provided usage data
            2. Calculates payment amounts based on pricing rates
            3. Fetches current token price (currently supports SOL only)
            4. Creates a split payment transaction (treasury fee + recipient payment)
            5. Signs the transaction with the provided private key
            6. Sends the transaction to Solana network
            7. Waits for confirmation at the specified commitment level
            8. Returns transaction signature and payment details

        **Payment Splitting:**
            The payment is automatically split between:
            - **Treasury**: Receives the processing fee (5% by default, configurable on service)
            - **Recipient**: Receives the net payment amount (95% by default)

        **Security Notes:**
            - Private key is used only in-memory for transaction signing
            - No key material is logged or persisted
            - Transaction is executed on-chain with full transparency
            - The treasury pubkey is configured on the settlement service and cannot be overridden

        **Args:**
            private_key: Solana wallet private key. Can be in JSON array format
                (e.g., "[1,2,3,...64 bytes...]") or base58 encoded string.
                Must be 32 or 64 bytes. WARNING: This is custodial-like behavior.
            usage: Usage data containing token counts. Supports same formats as
                `parse_usage` method. Can be raw usage data or already parsed.
            input_cost_per_million_usd: Cost per million input tokens in USD.
            output_cost_per_million_usd: Cost per million output tokens in USD.
            recipient_pubkey: Solana public key of the recipient wallet (base58 encoded).
                This wallet receives the net payment after fees.
            payment_token: Token to use for payment. Currently only "SOL" is supported
                for automatic settlement. Default: "SOL".
            skip_preflight: Whether to skip preflight simulation. Setting to True
                can speed up transactions but may result in failed transactions.
                Default: False.
            commitment: Solana commitment level for transaction confirmation:
                - "processed": Fastest, but may be rolled back
                - "confirmed": Recommended default, confirmed by cluster
                - "finalized": Slowest, but cannot be rolled back
                Default: "confirmed".

        **Returns:**
            Dict with payment details:
                - `status` (str): "paid" if successful, "skipped" if zero cost
                - `transaction_signature` (str, optional): Solana transaction signature
                - `pricing` (dict): Complete cost breakdown
                - `payment` (dict, optional): Payment details including:
                    - `total_amount_lamports` (int): Total payment in lamports
                    - `total_amount_sol` (float): Total payment in SOL
                    - `total_amount_usd` (float): Total payment in USD
                    - `treasury` (dict): Treasury payment details
                    - `recipient` (dict): Recipient payment details

        **Raises:**
            SettlementServiceError: If the settlement service returns an error.
                Common errors include:
                - Invalid private key format
                - Insufficient funds
                - Network errors
                - Transaction failures

        **Example:**
            ```python
            result = await client.settle(
                private_key="[1,2,3,...]",  # Wallet private key
                usage={"input_tokens": 1000, "output_tokens": 500},
                input_cost_per_million_usd=10.0,
                output_cost_per_million_usd=30.0,
                recipient_pubkey="RecipientPublicKeyHere",
                payment_token="SOL",
                commitment="confirmed"
            )
            # Returns:
            # {
            #     "status": "paid",
            #     "transaction_signature": "5j7s8K9...",
            #     "pricing": {...},
            #     "payment": {
            #         "total_amount_sol": 0.00125,
            #         "treasury": {"amount_sol": 0.0000625, ...},
            #         "recipient": {"amount_sol": 0.0011875, ...}
            #     }
            # }
            ```

        **Note:**
            The treasury_pubkey is automatically set from the SWARMS_TREASURY_PUBKEY
            environment variable on the settlement service and cannot be overridden.
            Settlement operations may take time due to blockchain confirmation. Increase
            the client timeout if you experience timeout errors even when payments succeed.
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

                response = await client.post(
                    f"{self.base_url}/v1/settlement/settle",
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            raise self._handle_http_error(e, "settle")
        except Exception as e:
            logger.error(
                f"Unexpected error calling settlement service settle: {e}",
                exc_info=True,
            )
            raise SettlementServiceError(
                message=f"Unexpected error during settle: {str(e)}",
                error_type="Unexpected error",
            )

    async def health_check(self) -> Dict[str, Any]:
        """
        Check if the settlement service is healthy.

        This method calls the settlement service's health check endpoint to verify
        that the service is running and responsive. Useful for monitoring and
        connection testing.

        **Returns:**
            Dict with health status information, typically including:
                - `status` (str): Service status (e.g., "healthy")
                - `service` (str): Service name
                - `version` (str): Service version

        **Raises:**
            SettlementServiceError: If the settlement service is unreachable or
                returns an error. This indicates the service may be down or
                experiencing issues.

        **Example:**
            ```python
            try:
                health = await client.health_check()
                print(f"Service status: {health['status']}")
                # Output: Service status: healthy
            except SettlementServiceError as e:
                print(f"Service is down: {e}")
            ```
        """
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                response = await client.get(f"{self.base_url}/health")
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            raise self._handle_http_error(e, "health_check")
        except Exception as e:
            logger.error(
                f"Unexpected error during health check: {e}",
                exc_info=True,
            )
            raise SettlementServiceError(
                message=f"Unexpected error during health_check: {str(e)}",
                error_type="Unexpected error",
            )
