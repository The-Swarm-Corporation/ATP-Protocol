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
from atp.encryption import ResponseEncryptor
from atp.schemas import PaymentToken
from atp.settlement_client import (
    SettlementServiceClient,
    SettlementServiceError,
)


class ATPSettlementMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware that automatically deducts payment from Solana wallets
    based on token usage for configured endpoints.

    This middleware intercepts responses from specified endpoints, extracts usage
    information (input/output tokens), calculates payment amounts, and executes
    Solana blockchain transactions to deduct payment before returning the response
    to the client.

    **Architecture & Design:**

    The middleware delegates all settlement logic to the ATP Settlement Service,
    ensuring immutable and centralized settlement operations. This design provides:
    - Centralized parsing logic for multiple API formats (OpenAI, Anthropic, Google, etc.)
    - Consistent payment calculation across all services
    - Immutable settlement logic that cannot be modified by individual services
    - Automatic handling of nested usage structures

    **Request Flow:**

    1. Request arrives at a configured endpoint
    2. Middleware extracts wallet private key from request headers
    3. Request is forwarded to the endpoint handler
    4. Response is intercepted and parsed for usage data
    5. Response is encrypted to prevent unauthorized access
    6. Usage data is sent to settlement service for parsing and payment calculation
    7. Payment transaction is executed on Solana blockchain
    8. Response is decrypted only after payment confirmation
    9. Response is returned to client with settlement details

    **Security Features:**

    - **Response Encryption**: Agent responses are encrypted before payment verification,
      ensuring users cannot see output until payment is confirmed on-chain.
    - **Payment Verification**: Responses are only decrypted after successful blockchain
      transaction confirmation (status="paid" with valid transaction signature).
    - **Error Handling**: Failed payments result in encrypted responses with error details,
      preventing unauthorized access to agent output.

    **Payment Splitting:**

    Payments are automatically split between:
    - **Treasury**: Receives the processing fee (configured via SWARMS_TREASURY_PUBKEY
      on settlement service). Default fee percentage is 5%.
    - **Recipient**: Receives the remainder (95% by default). This is the endpoint host's
      wallet specified via `recipient_pubkey`.

    **Usage Parsing:**

    The middleware sends the entire response body to the settlement service's
    `/v1/settlement/parse-usage` endpoint, which automatically handles:
    - Multiple API formats (OpenAI, Anthropic, Google/Gemini, Cohere, etc.)
    - Nested structures (usage.usage, meta.usage, statistics, etc.)
    - Recursive parsing for deeply nested usage objects
    - Normalization to standard format (input_tokens, output_tokens, total_tokens)

    **Error Handling:**

    The middleware provides two error handling modes:
    - **fail_on_settlement_error=False** (default): Returns encrypted response with
      settlement error details. Useful for debugging and graceful degradation.
    - **fail_on_settlement_error=True**: Raises HTTPException when settlement fails.
      Useful for strict payment requirements.

    **Response Modifications:**

    The middleware adds the following fields to responses:
    - `atp_usage`: Normalized usage data (input_tokens, output_tokens, total_tokens)
    - `atp_settlement`: Settlement details including transaction signature and payment breakdown
    - `atp_settlement_status`: Status of settlement ("paid", "failed", etc.)
    - `atp_message`: Informational message about response encryption status

    **Attributes:**

        allowed_endpoints (Set[str]): Set of endpoint paths to apply settlement to.
        input_cost_per_million_usd (float): Cost per million input tokens in USD.
        output_cost_per_million_usd (float): Cost per million output tokens in USD.
        wallet_private_key_header (str): HTTP header name for wallet private key.
        payment_token (PaymentToken): Token to use for payment (SOL or USDC).
        skip_preflight (bool): Whether to skip preflight simulation for Solana transactions.
        commitment (str): Solana commitment level (processed|confirmed|finalized).
        fail_on_settlement_error (bool): Whether to raise exception on settlement failure.
        settlement_service_client (SettlementServiceClient): Client for settlement service API.
        encryptor (ResponseEncryptor): Encryptor for protecting agent responses.

    **Example Usage:**

        ```python
        from fastapi import FastAPI
        from atp.middleware import ATPSettlementMiddleware
        from atp.schemas import PaymentToken

        app = FastAPI()

        app.add_middleware(
            ATPSettlementMiddleware,
            allowed_endpoints=["/v1/chat", "/v1/completions"],
            input_cost_per_million_usd=10.0,
            output_cost_per_million_usd=30.0,
            wallet_private_key_header="x-wallet-private-key",
            payment_token=PaymentToken.SOL,
            recipient_pubkey="YourPublicKeyHere",  # Required
            settlement_service_url="https://facilitator.swarms.world",  # Optional
            settlement_timeout=300.0,  # Optional, default 5 minutes
            fail_on_settlement_error=False,  # Optional, default False
        )

        @app.post("/v1/chat")
        async def chat(request: dict):
            # Your endpoint logic here
            # Response should include usage data in any supported format
            return {
                "response": "Hello!",
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "total_tokens": 30
                }
            }
        ```

    **Notes:**

    - The middleware only processes successful responses (status_code < 400).
    - If usage data cannot be parsed (no input_tokens, output_tokens, or total_tokens
      in the response), the middleware raises HTTP 422 with an error message.
    - Settlement operations may take time due to blockchain confirmation. Increase
      `settlement_timeout` if you experience timeout errors even when payments succeed.
    - The treasury pubkey is configured on the settlement service and cannot be
      overridden by the middleware.
    - Wallet private keys are passed directly via headers. For production, consider
      adding an API key layer or using secure key management.
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
        settlement_service_url: Optional[str] = None,
        fail_on_settlement_error: bool = False,
        settlement_timeout: Optional[float] = None,
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
            settlement_service_url: Base URL of the settlement service. If not provided, uses
                ATP_SETTLEMENT_URL environment variable (default: http://localhost:8001).
                The middleware always uses the settlement service for all settlement operations.
            fail_on_settlement_error: If True, raises HTTPException when settlement fails (default: False).
                If False, returns the response with settlement error info instead of failing the request.
            settlement_timeout: Timeout in seconds for settlement service requests. User-configurable parameter.
                Default: from ATP_SETTLEMENT_TIMEOUT env var or 300.0 (5 minutes). Settlement operations may
                take longer due to blockchain confirmation times. Increase this value if you experience timeout
                errors even when payments are successfully sent.
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
        # Note: Treasury pubkey is automatically set from SWARMS_TREASURY_PUBKEY
        # environment variable on the settlement service and cannot be overridden
        self.skip_preflight = skip_preflight
        self.commitment = commitment
        self.fail_on_settlement_error = fail_on_settlement_error
        # Always use settlement service - initialize client with config value or provided URL
        service_url = (
            settlement_service_url or config.ATP_SETTLEMENT_URL
        )
        self.settlement_service_client = SettlementServiceClient(
            base_url=service_url,
            timeout=settlement_timeout,
        )
        # Initialize encryptor for protecting agent responses
        self.encryptor = ResponseEncryptor()

    def _should_process(self, path: str) -> bool:
        """
        Check if the request path should be processed by this middleware.

        Args:
            path: The request URL path.

        Returns:
            True if the path is in the allowed endpoints set, False otherwise.
        """
        return path in self.allowed_endpoints

    def _extract_wallet_private_key(
        self, request: Request
    ) -> Optional[str]:
        """
        Extract wallet private key from request headers.

        The private key should be provided in the header specified by
        `wallet_private_key_header` (default: "x-wallet-private-key").
        The key can be in JSON array format (e.g., "[1,2,3,...]") or
        base58 string format.

        Args:
            request: The incoming HTTP request.

        Returns:
            The wallet private key string if found, None otherwise.
        """
        return request.headers.get(self.wallet_private_key_header)

    async def _parse_usage_from_response(
        self, response_body: bytes
    ) -> Optional[Dict[str, Any]]:
        """
        Parse usage information from response body using the settlement service.

        Delegates all usage parsing logic to the settlement service's parse-usage
        endpoint, which handles multiple formats and nested structures automatically.
        This centralizes all parsing logic in the immutable settlement service.

        Args:
            response_body: Raw response body bytes.

        Returns:
            Parsed usage dict with normalized keys (input_tokens, output_tokens, total_tokens),
            or None if parsing fails or no usage data is found.
        """
        try:
            body_str = response_body.decode("utf-8")
            if not body_str.strip():
                return None
            data = json.loads(body_str)

            # Send entire response body to settlement service for parsing
            # The service handles all format detection and nested structure traversal
            parsed_usage = await self.settlement_service_client.parse_usage(
                usage_data=data
            )

            # Check if we got valid token counts
            if (
                parsed_usage.get("input_tokens") is not None
                or parsed_usage.get("output_tokens") is not None
                or parsed_usage.get("total_tokens") is not None
            ):
                return parsed_usage

            return None
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug(
                f"Failed to parse response body for usage: {e}"
            )
            return None
        except SettlementServiceError as e:
            # If settlement service can't parse usage, log and return None
            logger.debug(
                f"Settlement service could not parse usage from response: {e}"
            )
            return None
        except Exception as e:
            logger.debug(
                f"Unexpected error parsing usage: {e}"
            )
            return None
        
    def log_to_marketplace(self):
        """
        Log the request to the marketplace and make it discoverable.

        This is a placeholder method for future marketplace integration.
        Currently does nothing but can be extended to log requests to a
        marketplace service for discovery and analytics.

        Note: This method is not currently called by the middleware.
        """
        pass 

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        """
        Process the request and apply settlement if applicable.

        This is the main middleware entry point that intercepts requests and responses.
        It handles the complete settlement flow including usage parsing, payment execution,
        and response encryption/decryption.

        **Flow:**

        1. Check if request path is in allowed endpoints
        2. Extract wallet private key from headers (if required)
        3. Forward request to endpoint handler
        4. Intercept response and parse usage data via settlement service
        5. Encrypt response to prevent unauthorized access
        6. Execute payment via settlement service
        7. Decrypt response only after payment confirmation
        8. Return response with settlement metadata

        **Args:**
            request: The incoming HTTP request.
            call_next: Callable to invoke the next middleware/endpoint handler.

        **Returns:**
            Response with settlement metadata added. Response body is encrypted until
            payment is confirmed. If payment fails, response remains encrypted with
            error details.

        **Raises:**
            HTTPException: If wallet is required but missing (402 Payment Required), or if
                `fail_on_settlement_error=True` and settlement fails.

        **Response Modifications:**
            - Adds `atp_usage` field with normalized token counts
            - Adds `atp_settlement` field with payment details
            - Adds `atp_settlement_status` field with payment status
            - Adds `atp_message` field with encryption status message
            - Removes `Content-Length` and `Content-Encoding` headers (recalculated)

        **Error Scenarios:**
            - Missing wallet (if required): Returns 402 Payment Required
            - No usage data: Raises 422 with message that endpoint must output
                input_tokens, output_tokens, or total_tokens (or equivalent usage fields)
            - Encryption failure: Returns 500 with error (response not exposed)
            - Settlement failure: Returns encrypted response with error details
                (or raises exception if `fail_on_settlement_error=True`)
        """
        path = request.url.path

        # Skip if not in allowed endpoints
        if not self._should_process(path):
            return await call_next(request)

        # Extract wallet private key
        private_key = self._extract_wallet_private_key(request)
        
        if not private_key:
            raise HTTPException(
                status_code=402,
                detail="Payment required. Missing wallet private key in header. Please provide a valid wallet private key and ensure payment succeeds. The header should be x-wallet-private-key.",
            )

        # Execute the endpoint
        response = await call_next(request)

        # Only process successful responses
        if response.status_code >= 400:
            return response

        # Parse usage from response using settlement service
        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        usage = await self._parse_usage_from_response(response_body)

        if not usage:
            logger.warning(
                f"No usage data found in response for {path}. "
                "Settlement service could not parse usage from response body."
            )
            raise HTTPException(
                status_code=422,
                detail=(
                    "Endpoint must include token usage in the response. "
                    "Response must contain at least one of: input_tokens, output_tokens, or total_tokens "
                    "(or equivalent fields such as prompt_tokens/completion_tokens in a usage object). "
                    f"No parseable usage data found for {path}."
                ),
            )

        # Encrypt the agent response before payment verification
        # This ensures users cannot see the output until payment is confirmed
        try:
            response_data = json.loads(response_body.decode("utf-8"))
            # Encrypt sensitive output fields (output, response, result, message)
            encrypted_response_data = self.encryptor.encrypt_response_data(
                response_data
            )
            # Store original encrypted data for later decryption
            original_encrypted_data = encrypted_response_data.copy()
        except Exception as e:
            logger.error(
                f"Failed to encrypt response: {e}. "
                "This is a security issue - cannot proceed without encryption.",
                exc_info=True,
            )
            # If encryption fails, we cannot securely proceed
            # Return error without exposing agent output
            error_response = {
                "error": "Internal server error",
                "message": "Failed to encrypt response. Please contact support.",
                "atp_usage": usage,
            }
            new_headers = dict(response.headers)
            new_headers.pop("content-length", None)
            new_headers.pop("Content-Length", None)
            new_headers.pop("content-encoding", None)
            new_headers.pop("Content-Encoding", None)
            return Response(
                content=json.dumps(error_response).encode("utf-8"),
                status_code=500,
                headers=new_headers,
                media_type="application/json",
            )

        # Calculate and deduct payment via settlement service
        payment_result = None
        settlement_error = None
        
        try:
            payment_result = await self.settlement_service_client.settle(
                private_key=private_key,
                usage=usage,
                input_cost_per_million_usd=self.input_cost_per_million_usd,
                output_cost_per_million_usd=self.output_cost_per_million_usd,
                recipient_pubkey=self._recipient_pubkey,
                payment_token=self.payment_token.value,
                skip_preflight=self.skip_preflight,
                commitment=self.commitment,
            )
        except SettlementServiceError as e:
            # Handle settlement service errors with detailed information
            # The error already contains extracted details from the service response
            error_dict = e.to_dict()
            
            # Determine if this is a client error (4xx) or server error (5xx)
            is_client_error = e.status_code and 400 <= e.status_code < 500
            
            if self.fail_on_settlement_error:
                # Raise HTTPException with appropriate status code
                status_code = e.status_code or 500
                detail = e.error_detail or str(e)
                raise HTTPException(
                    status_code=status_code,
                    detail=detail,
                )
            
            # Store error info to include in response
            settlement_error = error_dict.copy()
            settlement_error["type"] = e.error_type or error_dict.get("type", "Settlement error")
            
            # Log with appropriate level based on error type
            if is_client_error:
                logger.warning(
                    f"Settlement failed (client error {e.status_code}): {e.error_detail or str(e)}"
                )
            else:
                logger.error(
                    f"Settlement failed (server error {e.status_code or 'unknown'}): {e.error_detail or str(e)}"
                )
        except HTTPException:
            # Re-raise HTTPExceptions (these are intentional errors like 401, 403, etc.)
            if self.fail_on_settlement_error:
                raise
            settlement_error = {
                "error": "Settlement failed",
                "status_code": 500,
                "detail": "Settlement service returned an error",
            }
            logger.warning("Settlement failed with HTTPException, but continuing with response")
        except Exception as e:
            # Handle unexpected errors
            logger.error(f"Unexpected settlement error: {e}", exc_info=True)
            if self.fail_on_settlement_error:
                raise HTTPException(
                    status_code=500,
                    detail=f"Settlement failed: {str(e)}",
                )
            # Store error info to include in response
            settlement_error = {
                "error": "Settlement failed",
                "message": str(e),
                "type": type(e).__name__,
            }
            logger.warning(
                f"Settlement failed but continuing with response: {e}"
            )

        # Process payment result and decrypt response only if payment succeeded
        try:
            # Start with the encrypted response data
            final_response_data = original_encrypted_data.copy()
            final_response_data["atp_usage"] = usage
            
            # Check if payment was successful
            payment_succeeded = False
            if payment_result:
                # Check if payment status is "paid"
                payment_status = payment_result.get("status", "").lower()
                # Also check for transaction signature as additional confirmation
                has_transaction = bool(
                    payment_result.get("transaction_signature")
                )
                
                if payment_status == "paid" and has_transaction:
                    payment_succeeded = True
                    # Decrypt the response now that payment is confirmed
                    final_response_data = self.encryptor.decrypt_response_data(
                        final_response_data
                    )
                    logger.info(
                        f"Payment confirmed (tx: {payment_result.get('transaction_signature', 'N/A')[:16]}...), "
                        "response decrypted"
                    )
                else:
                    logger.warning(
                        f"Payment not confirmed. Status: '{payment_status}', "
                        f"Has transaction: {has_transaction}. "
                        "Response will remain encrypted."
                    )
                final_response_data["atp_settlement"] = payment_result
            elif settlement_error:
                # Payment failed - keep response encrypted
                final_response_data["atp_settlement"] = settlement_error
                final_response_data["atp_settlement_status"] = "failed"
                logger.warning(
                    "Payment failed, response remains encrypted. "
                    "User cannot see agent output."
                )
            
            # If payment didn't succeed, add a message indicating the response is encrypted
            if not payment_succeeded:
                final_response_data["atp_message"] = (
                    "Agent response is encrypted. Payment required to decrypt. "
                    "Please provide a valid wallet private key and ensure payment succeeds."
                )
            
            response_body = json.dumps(final_response_data).encode("utf-8")
        except Exception as e:
            logger.error(
                f"Failed to process payment and decrypt response: {e}",
                exc_info=True,
            )
            # On error, return encrypted response with error info
            try:
                error_response = original_encrypted_data.copy()
                error_response["atp_usage"] = usage
                error_response["atp_settlement_error"] = {
                    "error": "Failed to process payment",
                    "message": str(e),
                }
                error_response["atp_message"] = (
                    "Agent response is encrypted. Payment processing failed."
                )
                response_body = json.dumps(error_response).encode("utf-8")
            except Exception as e2:
                logger.error(
                    f"Failed to create error response: {e2}", exc_info=True
                )
                # Last resort: return original encrypted response
                response_body = json.dumps(original_encrypted_data).encode(
                    "utf-8"
                )

        # Create new headers without Content-Length since we modified the body
        # Starlette/FastAPI will recalculate it automatically
        new_headers = dict(response.headers)
        # Remove Content-Length and Content-Encoding headers as they're no longer valid
        new_headers.pop("content-length", None)
        new_headers.pop("Content-Length", None)
        new_headers.pop("content-encoding", None)
        new_headers.pop("Content-Encoding", None)

        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=new_headers,
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
            recipient_pubkey="YourPublicKeyHere",  # Required: recipient wallet public key
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
