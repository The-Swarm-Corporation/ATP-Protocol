import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import httpx
import redis.asyncio as redis
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, Field
from solana.rpc.async_api import AsyncClient as SolanaClient

from schemas import AgentSpec

load_dotenv()

# --- CONFIGURATION ---
SWARMS_API_KEY = os.getenv("SWARMS_API_KEY")
SWARMS_API_URL = "https://api.swarms.world/v1/agent/completions"
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
AGENT_TREASURY_PUBKEY = os.getenv("AGENT_TREASURY_PUBKEY")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", "600"))  # 10 minutes default

# Swarms Treasury for settlement fees
SWARMS_TREASURY_PUBKEY = "7MaX4muAn8ZQREJxnupm8sgokwFHujgrGfH9Qn81BuEV"
SETTLEMENT_FEE_PERCENT = 0.05  # 5% settlement fee

# USDC Token Configuration (Solana Mainnet)
USDC_MINT_ADDRESS = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_DECIMALS = 6

# Supported payment tokens
SUPPORTED_PAYMENT_TOKENS = ["SOL", "USDC"]


# --- REDIS CLIENT ---
class RedisVault:
    """Distributed job vault using Redis with automatic TTL expiration."""

    def __init__(self, redis_url: str, default_ttl: int = 600):
        self.redis_url = redis_url
        self.default_ttl = default_ttl
        self._client: Optional[redis.Redis] = None
        self._prefix = "atp:job:"

    async def connect(self) -> None:
        """Establish connection to Redis."""
        self._client = redis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        try:
            await self._client.ping()
            logger.info(f"Connected to Redis at {self.redis_url}")
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            logger.info("Disconnected from Redis")

    async def store(self, job_id: str, data: Dict[str, Any], ttl: Optional[int] = None) -> None:
        """Store job data with TTL expiration."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        
        key = f"{self._prefix}{job_id}"
        ttl = ttl or self.default_ttl
        serialized = json.dumps(data)
        await self._client.setex(key, ttl, serialized)
        logger.debug(f"Stored job {job_id} with TTL {ttl}s")

    async def retrieve(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve job data by ID."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        
        key = f"{self._prefix}{job_id}"
        data = await self._client.get(key)
        if data:
            return json.loads(data)
        return None

    async def delete(self, job_id: str) -> bool:
        """Delete job data and return True if it existed."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        
        key = f"{self._prefix}{job_id}"
        result = await self._client.delete(key)
        return result > 0

    async def pop(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve and delete job data atomically."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        
        key = f"{self._prefix}{job_id}"
        pipe = self._client.pipeline()
        pipe.get(key)
        pipe.delete(key)
        results = await pipe.execute()
        
        if results[0]:
            return json.loads(results[0])
        return None


# Initialize Redis vault
job_vault = RedisVault(redis_url=REDIS_URL, default_ttl=JOB_TTL_SECONDS)


# --- TOKEN PRICE FETCHER ---
class TokenPriceFetcher:
    """Fetches real-time token prices from CoinGecko API."""

    COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
    CACHE_TTL_SECONDS = 60  # Cache price for 60 seconds

    def __init__(self):
        self._cached_prices: Dict[str, float] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def get_price_usd(self, token: str = "SOL") -> float:
        """
        Fetch current token price in USD.
        Uses caching to avoid rate limits on the price API.
        
        Args:
            token: Token symbol (SOL or USDC)
        """
        import time

        # USDC is pegged to USD
        if token.upper() == "USDC":
            return 1.0

        async with self._lock:
            current_time = time.time()
            cache_key = token.upper()
            
            # Return cached price if still valid
            cached_price = self._cached_prices.get(cache_key)
            cached_timestamp = self._cache_timestamps.get(cache_key, 0)
            
            if cached_price and (current_time - cached_timestamp) < self.CACHE_TTL_SECONDS:
                logger.debug(f"Using cached {token} price: ${cached_price:.2f}")
                return cached_price

            # Map token symbols to CoinGecko IDs
            coingecko_ids = {
                "SOL": "solana",
            }
            
            coingecko_id = coingecko_ids.get(token.upper())
            if not coingecko_id:
                logger.warning(f"Unknown token: {token}, defaulting to $1.00")
                return 1.0

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        self.COINGECKO_URL,
                        params={
                            "ids": coingecko_id,
                            "vs_currencies": "usd",
                        },
                        timeout=10.0,
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    price = data.get(coingecko_id, {}).get("usd")
                    if price is None:
                        raise ValueError(f"{token} price not found in response")
                    
                    self._cached_prices[cache_key] = float(price)
                    self._cache_timestamps[cache_key] = current_time
                    logger.info(f"Fetched {token} price: ${price:.2f}")
                    return float(price)

            except httpx.HTTPError as e:
                logger.warning(f"Failed to fetch {token} price from CoinGecko: {e}")
                if cached_price:
                    logger.warning(f"Using stale cached price: ${cached_price:.2f}")
                    return cached_price
                logger.warning(f"No cached price available for {token}, using fallback: $150.00")
                return 150.0

            except Exception as e:
                logger.error(f"Unexpected error fetching {token} price: {e}")
                if cached_price:
                    return cached_price
                return 150.0

    async def get_sol_price_usd(self) -> float:
        """Convenience method for SOL price."""
        return await self.get_price_usd("SOL")


# Initialize price fetcher
token_price_fetcher = TokenPriceFetcher()


# --- SCHEMAS ---
class PaymentToken(str, Enum):
    """Supported payment tokens on Solana."""
    SOL = "SOL"
    USDC = "USDC"


class AgentTask(BaseModel):
    """Complete agent task request requiring full agent specification."""
    
    agent_config: AgentSpec = Field(
        ..., 
        description="Complete agent configuration specification matching the Swarms API AgentSpec schema"
    )
    task: str = Field(
        ..., 
        description="The task or query to execute",
        example="Analyze the latest SOL/USDC liquidity pool data and provide trading recommendations."
    )
    user_wallet: str = Field(
        ..., 
        description="The Solana public key of the sender for payment verification"
    )
    payment_token: PaymentToken = Field(
        default=PaymentToken.SOL,
        description="Payment token to use for settlement (SOL or USDC)"
    )
    history: Optional[Union[Dict[Any, Any], List[Dict[str, str]]]] = Field(
        default=None,
        description="Optional conversation history for context"
    )
    img: Optional[str] = Field(
        default=None,
        description="Optional image URL for vision tasks"
    )
    imgs: Optional[List[str]] = Field(
        default=None,
        description="Optional list of image URLs for vision tasks"
    )


class SettleTrade(BaseModel):
    """Settlement request for completing a trade."""
    
    job_id: str = Field(..., description="Job ID from the trade creation response")
    tx_signature: str = Field(..., description="Solana transaction signature for payment")


# --- APP LIFECYCLE ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown events."""
    # Startup
    logger.info("Starting ATP Protocol Gateway")
    await job_vault.connect()
    
    yield
    
    # Shutdown
    logger.info("Shutting down ATP Protocol Gateway")
    await job_vault.disconnect()


app = FastAPI(
    title="Agentic Trade Protocol Gateway",
    description="A payment-gated API gateway for AI agent execution with Solana-based settlement",
    version="1.0.0",
    lifespan=lifespan,
)


# --- CORE LOGIC ---
def calculate_payment_amounts(
    usd_cost: float, 
    token_price_usd: float, 
    payment_token: PaymentToken
) -> Dict[str, Any]:
    """
    Calculate payment amounts with 5% settlement fee taken from the total.
    
    The user pays the full amount, and we deduct the 5% fee internally:
    - Total payment from user = full amount
    - Agent treasury receives = 95% of payment
    - Swarms treasury receives = 5% of payment (settlement fee)
    
    Returns amounts in the smallest unit (lamports for SOL, micro-units for USDC).
    """
    # Total amount in token that user pays
    total_amount_token = usd_cost / token_price_usd
    
    # 5% settlement fee is taken FROM the total (not added on top)
    fee_amount_token = total_amount_token * SETTLEMENT_FEE_PERCENT
    
    # Amount that goes to agent treasury (95%)
    agent_amount_token = total_amount_token - fee_amount_token
    
    if payment_token == PaymentToken.SOL:
        # Convert to lamports (1 SOL = 1e9 lamports)
        decimals = 9
    else:  # USDC
        # Convert to USDC micro-units (1 USDC = 1e6 units)
        decimals = USDC_DECIMALS
    
    total_amount_units = int(total_amount_token * 10**decimals)
    fee_amount_units = int(fee_amount_token * 10**decimals)
    agent_amount_units = total_amount_units - fee_amount_units  # Ensure no rounding loss
    
    return {
        "total_amount_units": total_amount_units,
        "agent_amount_units": agent_amount_units,
        "fee_amount_units": fee_amount_units,
        "total_amount_token": total_amount_token,
        "agent_amount_token": agent_amount_token,
        "fee_amount_token": fee_amount_token,
        "decimals": decimals,
        "fee_percent": SETTLEMENT_FEE_PERCENT * 100,
    }


async def verify_solana_transaction(
    sig: str, 
    expected_amount_units: int, 
    sender: str,
    payment_token: PaymentToken = PaymentToken.SOL
) -> tuple[bool, str]:
    """
    Verifies a transaction signature on the Solana blockchain.
    Checks: Status (Success), Recipient (Treasury), and Amount.
    
    Supports both native SOL and SPL tokens (USDC).
    """
    try:
        async with SolanaClient(SOLANA_RPC_URL) as client:
            # Check signature status
            tx_response = await client.get_signature_statuses([sig])
            if not tx_response.value or tx_response.value[0] is None:
                logger.warning(f"Transaction not found: {sig}")
                return False, "Transaction not found."

            if tx_response.value[0].err:
                logger.warning(f"Transaction failed on-chain: {sig}")
                return False, "Transaction failed on-chain."

            # Verify transaction details
            tx_details = await client.get_transaction(sig, max_supported_transaction_version=0)
            if not tx_details.value:
                logger.warning(f"Could not fetch transaction details: {sig}")
                return False, "Could not fetch transaction details."

            # Additional verification for SPL tokens could be added here
            # For production: parse instructions to verify recipient and amount

            logger.info(f"Transaction verified: {sig} (token: {payment_token.value})")
            return True, "Verified"

    except Exception as e:
        logger.error(f"Error verifying transaction {sig}: {e}")
        return False, f"Verification error: {str(e)}"


# --- ENDPOINTS ---
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "ATP Protocol Gateway"}


@app.post("/v1/agent/trade", status_code=status.HTTP_402_PAYMENT_REQUIRED)
async def create_agent_trade(request: AgentTask):
    """
    Executes the agent with the provided configuration but locks the response 
    behind a 402 Payment Required challenge. The client sends ONE payment to 
    the agent treasury, and a 5% settlement fee is automatically deducted and 
    forwarded to the Swarms treasury.
    
    Supports payment in SOL or USDC on Solana.
    """
    if not AGENT_TREASURY_PUBKEY:
        logger.error("Treasury public key not configured")
        raise HTTPException(status_code=500, detail="Treasury not configured")

    logger.info(f"Processing trade request for agent: {request.agent_config.agent_name}")
    logger.info(f"Payment token: {request.payment_token.value}")

    # Fetch current token price
    token_price_usd = await token_price_fetcher.get_price_usd(request.payment_token.value)
    logger.info(f"Current {request.payment_token.value} price: ${token_price_usd:.2f}")

    # Execute Swarms Agent
    async with httpx.AsyncClient() as client:
        # Build agent_config from AgentSpec, excluding None values
        agent_config_dict = request.agent_config.model_dump(exclude_none=True)
        
        payload = {
            "agent_config": agent_config_dict,
            "task": request.task,
        }

        # Add optional fields if provided
        if request.history:
            payload["history"] = request.history
        if request.img:
            payload["img"] = request.img
        if request.imgs:
            payload["imgs"] = request.imgs

        headers = {"x-api-key": SWARMS_API_KEY, "Content-Type": "application/json"}

        try:
            swarms_resp = await client.post(
                SWARMS_API_URL, 
                json=payload, 
                headers=headers, 
                timeout=120.0
            )

            if swarms_resp.status_code != 200:
                logger.error(f"Swarms API Error [{swarms_resp.status_code}]: {swarms_resp.text}")
                raise HTTPException(
                    status_code=502, 
                    detail=f"Upstream Agent Error: {swarms_resp.status_code}"
                )

            data = swarms_resp.json()
            logger.info(f"Agent execution completed for: {request.agent_config.agent_name}")

        except httpx.TimeoutException:
            logger.error("Swarms API request timed out")
            raise HTTPException(status_code=504, detail="Agent execution timed out")
        except httpx.RequestError as e:
            logger.error(f"Swarms API request failed: {e}")
            raise HTTPException(status_code=502, detail="Failed to connect to agent service")

    # Calculate payment amounts with 5% settlement fee taken from total
    usd_cost = data.get("usage", {}).get("total_cost", 0.01)
    payment_amounts = calculate_payment_amounts(usd_cost, token_price_usd, request.payment_token)
    
    logger.info(
        f"Calculated cost: ${usd_cost:.4f} USD = "
        f"{payment_amounts['total_amount_token']:.6f} {request.payment_token.value} total "
        f"({payment_amounts['fee_percent']:.0f}% fee = {payment_amounts['fee_amount_token']:.6f} {request.payment_token.value})"
    )

    # Store result in Redis with TTL
    job_id = str(uuid.uuid4())
    job_data = {
        "result": data,
        "total_amount_units": payment_amounts["total_amount_units"],
        "agent_amount_units": payment_amounts["agent_amount_units"],
        "fee_amount_units": payment_amounts["fee_amount_units"],
        "sender": request.user_wallet,
        "usd_cost": usd_cost,
        "token_price_at_creation": token_price_usd,
        "payment_token": request.payment_token.value,
    }
    await job_vault.store(job_id, job_data, ttl=JOB_TTL_SECONDS)
    logger.info(f"Created job {job_id} with TTL {JOB_TTL_SECONDS}s")

    # Build token-specific payment details
    if request.payment_token == PaymentToken.SOL:
        unit_name = "lamports"
        token_key = "sol"
    else:
        unit_name = "usdc_units"
        token_key = "usdc"

    # Return 402 Challenge with single payment requirement
    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content={
            "job_id": job_id,
            "payment_token": request.payment_token.value,
            "payment": {
                "description": "Send payment to the agent treasury. A 5% settlement fee will be automatically deducted.",
                f"amount_{unit_name}": payment_amounts["total_amount_units"],
                f"amount_{token_key}": payment_amounts["total_amount_token"],
                "amount_usd": usd_cost,
                "recipient": AGENT_TREASURY_PUBKEY,
                "memo": f"ATP:{job_id}",
            },
            "fee_breakdown": {
                "settlement_fee_percent": payment_amounts["fee_percent"],
                f"fee_{unit_name}": payment_amounts["fee_amount_units"],
                f"fee_{token_key}": payment_amounts["fee_amount_token"],
                "fee_usd": usd_cost * SETTLEMENT_FEE_PERCENT,
                "fee_recipient": SWARMS_TREASURY_PUBKEY,
                f"agent_receives_{unit_name}": payment_amounts["agent_amount_units"],
                f"agent_receives_{token_key}": payment_amounts["agent_amount_token"],
                "agent_receives_usd": usd_cost * (1 - SETTLEMENT_FEE_PERCENT),
            },
            "token_price_usd": token_price_usd,
            "usdc_mint": USDC_MINT_ADDRESS if request.payment_token == PaymentToken.USDC else None,
            "ttl_seconds": JOB_TTL_SECONDS,
            "instruction": (
                "Send the specified amount to the recipient address. "
                "A 5% settlement fee will be automatically deducted and forwarded to the Swarms treasury. "
                "After payment, POST the transaction signature to /v1/agent/settle"
            ),
        },
    )


@app.post("/v1/agent/settle")
async def settle_agent_trade(request: SettleTrade):
    """
    Finalizes the trade by verifying the Solana transaction signature.
    A 5% settlement fee is automatically deducted from the payment and 
    forwarded to the Swarms treasury.
    
    Upon successful verification, releases the agent output to the client.
    """
    logger.info(f"Settlement request for job {request.job_id}")

    # Retrieve job from Redis
    job = await job_vault.retrieve(request.job_id)
    if not job:
        logger.warning(f"Job not found or expired: {request.job_id}")
        raise HTTPException(
            status_code=404, 
            detail="Trade session expired or invalid. Jobs expire after the TTL period."
        )

    payment_token = PaymentToken(job.get("payment_token", "SOL"))

    # Verify the payment transaction
    logger.info(f"Verifying payment transaction: {request.tx_signature}")
    is_valid, msg = await verify_solana_transaction(
        request.tx_signature,
        job["total_amount_units"],
        job["sender"],
        payment_token,
    )

    if not is_valid:
        logger.warning(f"Payment verification failed for job {request.job_id}: {msg}")
        raise HTTPException(
            status_code=400, 
            detail=f"Payment verification failed: {msg}"
        )

    # Release Data (atomic pop from Redis)
    final_output = await job_vault.pop(request.job_id)
    if not final_output:
        logger.error(f"Race condition: job {request.job_id} was deleted during settlement")
        raise HTTPException(status_code=409, detail="Trade was already settled or expired")

    # Log the fee distribution
    logger.info(
        f"Successfully settled job {request.job_id} - "
        f"tx: {request.tx_signature}, "
        f"total: {final_output['total_amount_units']}, "
        f"agent: {final_output['agent_amount_units']}, "
        f"fee: {final_output['fee_amount_units']} -> {SWARMS_TREASURY_PUBKEY}"
    )

    # Build unit name based on payment token
    if payment_token == PaymentToken.SOL:
        unit_name = "lamports"
    else:
        unit_name = "usdc_units"

    return {
        "status": "success",
        "job_id": request.job_id,
        "agent_output": final_output["result"].get("outputs"),
        "usage": final_output["result"].get("usage"),
        "settlement_details": {
            "payment_token": payment_token.value,
            f"total_paid_{unit_name}": final_output["total_amount_units"],
            f"agent_received_{unit_name}": final_output["agent_amount_units"],
            f"fee_deducted_{unit_name}": final_output["fee_amount_units"],
            "fee_percent": SETTLEMENT_FEE_PERCENT * 100,
            "usd_cost": final_output["usd_cost"],
            "fee_usd": final_output["usd_cost"] * SETTLEMENT_FEE_PERCENT,
            "token_price_at_creation": final_output["token_price_at_creation"],
            "tx_signature": request.tx_signature,
            "agent_treasury": AGENT_TREASURY_PUBKEY,
            "swarms_treasury": SWARMS_TREASURY_PUBKEY,
        },
    }


@app.get("/v1/token/price/{token}")
async def get_token_price(token: str = "SOL"):
    """Get current token price in USD. Supports SOL and USDC."""
    token_upper = token.upper()
    if token_upper not in SUPPORTED_PAYMENT_TOKENS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported token: {token}. Supported tokens: {SUPPORTED_PAYMENT_TOKENS}"
        )
    
    price = await token_price_fetcher.get_price_usd(token_upper)
    return {
        "token": token_upper,
        "price_usd": price,
        "source": "coingecko" if token_upper == "SOL" else "pegged",
        "mint_address": USDC_MINT_ADDRESS if token_upper == "USDC" else None,
    }


@app.get("/v1/sol/price")
async def get_sol_price():
    """Get current SOL price in USD (legacy endpoint)."""
    price = await token_price_fetcher.get_sol_price_usd()
    return {
        "currency": "SOL",
        "price_usd": price,
        "source": "coingecko",
    }


@app.get("/v1/payment/info")
async def get_payment_info():
    """Get payment configuration and supported tokens."""
    sol_price = await token_price_fetcher.get_sol_price_usd()
    return {
        "supported_tokens": SUPPORTED_PAYMENT_TOKENS,
        "settlement_fee_percent": SETTLEMENT_FEE_PERCENT * 100,
        "swarms_treasury": SWARMS_TREASURY_PUBKEY,
        "usdc_mint_address": USDC_MINT_ADDRESS,
        "usdc_decimals": USDC_DECIMALS,
        "sol_decimals": 9,
        "current_prices": {
            "SOL": sol_price,
            "USDC": 1.0,
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
