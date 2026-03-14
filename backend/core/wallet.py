"""
WDK (Wallet Development Kit) integration for sending USDT tips.
Docs: https://docs.wdk.tether.io/
"""
import httpx
from loguru import logger
from backend.config import config


class WalletClient:
    """HTTP client for the Tether WDK API."""

    def __init__(self):
        self.endpoint = config.wdk_endpoint.rstrip("/")
        self.api_key = config.wdk_api_key
        self.wallet_address = config.wdk_wallet_address
        self.default_token = config.default_token
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def get_balance(self) -> dict:
        """Fetch current wallet balance."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.endpoint}/wallet/balance",
                headers=self._headers,
                params={"address": self.wallet_address, "token": self.default_token},
            )
            response.raise_for_status()
            return response.json()

    async def send_tip(
        self,
        recipient_address: str,
        amount: float,
        token: str | None = None,
        memo: str = "",
    ) -> dict:
        """
        Send a tip to a creator's wallet address.

        Args:
            recipient_address: Creator's WDK wallet address
            amount: Amount to send (capped at MAX_TIP_PER_VIDEO)
            token: Token type (defaults to DEFAULT_TOKEN / USDT)
            memo: Optional transaction memo

        Returns:
            Transaction response with tx_hash
        """
        token = token or self.default_token
        amount = min(amount, config.max_tip_per_video)

        payload = {
            "from": self.wallet_address,
            "to": recipient_address,
            "amount": str(amount),
            "token": token,
            "memo": memo,
        }

        logger.info(f"Sending {amount} {token} tip to {recipient_address}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.endpoint}/transactions/send",
                headers=self._headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        logger.info(f"Tip sent — tx_hash: {result.get('tx_hash')}")
        return result

    async def get_transaction(self, tx_hash: str) -> dict:
        """Check the status of a transaction."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.endpoint}/transactions/{tx_hash}",
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json()


# Singleton
wallet_client = WalletClient()
