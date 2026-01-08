from __future__ import annotations

import asyncio
from typing import Dict

import httpx
from loguru import logger


class TokenPriceFetcher:
    """Fetches real-time token prices from CoinGecko API."""

    COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
    CACHE_TTL_SECONDS = 60  # Cache price for 60 seconds

    def __init__(self):
        self._cached_prices: Dict[str, float] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def get_price_usd(self, token: str = "SOL") -> float:
        import time

        # USDC is pegged to USD
        if token.upper() == "USDC":
            return 1.0

        async with self._lock:
            current_time = time.time()
            cache_key = token.upper()

            cached_price = self._cached_prices.get(cache_key)
            cached_timestamp = self._cache_timestamps.get(
                cache_key, 0
            )
            if (
                cached_price
                and (current_time - cached_timestamp)
                < self.CACHE_TTL_SECONDS
            ):
                return cached_price

            coingecko_ids = {"SOL": "solana"}
            coingecko_id = coingecko_ids.get(token.upper())
            if not coingecko_id:
                logger.warning(
                    f"Unknown token: {token}, defaulting to $1.00"
                )
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
                        raise ValueError(
                            f"{token} price not found in response"
                        )

                    self._cached_prices[cache_key] = float(price)
                    self._cache_timestamps[cache_key] = current_time
                    return float(price)

            except httpx.HTTPError as e:
                logger.warning(
                    f"Failed to fetch {token} price from CoinGecko: {e}"
                )
                if cached_price:
                    return cached_price
                return 150.0
            except Exception as e:
                logger.error(
                    f"Unexpected error fetching {token} price: {e}"
                )
                if cached_price:
                    return cached_price
                return 150.0

    async def get_sol_price_usd(self) -> float:
        return await self.get_price_usd("SOL")


token_price_fetcher = TokenPriceFetcher()


# if __name__ == "__main__":
#     print(asyncio.run(token_price_fetcher.get_price_usd("SOL")))
