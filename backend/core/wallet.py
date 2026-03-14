"""
TipMind Wallet Integration
--------------------------
WDKWallet  — calls a running WDK Node.js service (https://docs.wdk.tether.io/)
              via its HTTP REST wrapper at WDK_ENDPOINT.
MockWallet — drop-in fallback for local dev / demo when WDK is not configured.
WalletFactory.create() — returns the right implementation automatically.

All transactions are logged with prefix [WALLET].
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import random
import time
import uuid
from abc import ABC, abstractmethod

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import config
from backend.core.event_bus import event_bus, EventType
from backend.data.models import TipTransaction, TipTransactionORM


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class BaseWallet(ABC):
    """Common interface for all wallet implementations."""

    @abstractmethod
    async def send_tip(
        self,
        to_address: str,
        amount: float,
        token: str = "USDT",
    ) -> TipTransaction:
        """Send a tip and return a TipTransaction pydantic model."""

    @abstractmethod
    async def get_balance(self, token: str = "USDT") -> float:
        """Return available balance for the given token."""

    @abstractmethod
    async def get_transaction_status(self, tx_hash: str) -> str:
        """Return transaction status: 'pending' | 'confirmed' | 'failed'."""

    @abstractmethod
    async def get_wallet_address(self) -> str:
        """Return the wallet's public address."""


# ---------------------------------------------------------------------------
# WDKWallet  — real integration
# ---------------------------------------------------------------------------

class WDKWallet(BaseWallet):
    """
    Talks to a WDK Node.js microservice via HTTP.

    The microservice wraps @tetherto/wdk and exposes:
      POST /send          { to, amount, token }  → { tx_hash, fee }
      GET  /balance       ?token=USDT            → { balance }
      GET  /tx/:hash                             → { status }
      GET  /address                              → { address }

    Env vars consumed: WDK_ENDPOINT, WDK_API_KEY, WDK_WALLET_ADDRESS
    """

    def __init__(self) -> None:
        self._endpoint = config.wdk_endpoint.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {config.wdk_api_key}",
            "Content-Type": "application/json",
        }
        self._from_wallet = config.wdk_wallet_address

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_tip(
        self,
        to_address: str,
        amount: float,
        token: str = "USDT",
    ) -> TipTransaction:
        amount = min(amount, config.max_tip_per_video)
        logger.info(f"[WALLET] Checking balance before sending {amount} {token}")

        balance = await self.get_balance(token)
        if balance < amount:
            raise ValueError(
                f"[WALLET] Insufficient balance: have {balance} {token}, need {amount}"
            )

        logger.info(f"[WALLET] Sending {amount} {token} → {to_address}")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._endpoint}/send",
                headers=self._headers,
                json={"to": to_address, "amount": amount, "token": token},
            )
            resp.raise_for_status()
            data = resp.json()

        tx_hash = data.get("tx_hash") or data.get("hash")
        logger.info(f"[WALLET] Transaction signed & broadcast — tx_hash={tx_hash}")

        tx = TipTransaction(
            tx_hash=tx_hash,
            from_wallet=self._from_wallet,
            to_wallet=to_address,
            amount=amount,
            token=token,
            creator_id=to_address,
            trigger_type="SWARM",
            status="confirmed",
        )

        await event_bus.publish(EventType.TIP_EXECUTED, {
            "tx_hash": tx_hash,
            "to": to_address,
            "amount": amount,
            "token": token,
        })
        return tx

    async def get_balance(self, token: str = "USDT") -> float:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._endpoint}/balance",
                headers=self._headers,
                params={"token": token},
            )
            resp.raise_for_status()
            data = resp.json()
        balance = float(data.get("balance", 0))
        logger.debug(f"[WALLET] Balance: {balance} {token}")
        return balance

    async def get_transaction_status(self, tx_hash: str) -> str:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._endpoint}/tx/{tx_hash}",
                headers=self._headers,
            )
            resp.raise_for_status()
            data = resp.json()
        status = data.get("status", "pending")
        logger.debug(f"[WALLET] tx {tx_hash} status: {status}")
        return status

    async def get_wallet_address(self) -> str:
        if self._from_wallet:
            return self._from_wallet
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self._endpoint}/address", headers=self._headers)
            resp.raise_for_status()
            return resp.json().get("address", "")


# ---------------------------------------------------------------------------
# MockWallet  — demo / dev fallback
# ---------------------------------------------------------------------------

class MockWallet(BaseWallet):
    """
    In-memory mock wallet for local dev and demos.
    - Generates realistic fake tx hashes
    - Simulates 200–800 ms network delay
    - Tracks mock balances accurately
    """

    _MOCK_ADDRESS = "TGhMockWalletTipMind1234567890abcdef"

    def __init__(self, initial_balance: float = 1000.0) -> None:
        self._balances: dict[str, float] = {"USDT": initial_balance, "XAUT": 1.0, "BTC": 0.05}
        self._txs: dict[str, str] = {}  # tx_hash → status
        logger.info(f"[WALLET] MockWallet initialized with {initial_balance} USDT")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _simulate_network() -> None:
        await asyncio.sleep(random.uniform(0.2, 0.8))

    @staticmethod
    def _fake_tx_hash() -> str:
        seed = f"{uuid.uuid4()}{time.time_ns()}"
        return hashlib.sha256(seed.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_tip(
        self,
        to_address: str,
        amount: float,
        token: str = "USDT",
    ) -> TipTransaction:
        amount = min(amount, config.max_tip_per_video)
        await self._simulate_network()

        balance = self._balances.get(token, 0.0)
        if balance < amount:
            raise ValueError(
                f"[WALLET] Mock insufficient balance: have {balance} {token}, need {amount}"
            )

        self._balances[token] = round(balance - amount, 6)
        tx_hash = self._fake_tx_hash()
        self._txs[tx_hash] = "confirmed"

        logger.info(
            f"[WALLET] Mock tip sent — {amount} {token} → {to_address} "
            f"| tx={tx_hash[:16]}... | balance left={self._balances[token]} {token}"
        )

        tx = TipTransaction(
            tx_hash=tx_hash,
            from_wallet=self._MOCK_ADDRESS,
            to_wallet=to_address,
            amount=amount,
            token=token,
            creator_id=to_address,
            trigger_type="SWARM",
            status="confirmed",
        )

        await event_bus.publish(EventType.TIP_EXECUTED, {
            "tx_hash": tx_hash,
            "to": to_address,
            "amount": amount,
            "token": token,
            "mock": True,
        })
        return tx

    async def get_balance(self, token: str = "USDT") -> float:
        await self._simulate_network()
        balance = self._balances.get(token, 0.0)
        logger.debug(f"[WALLET] Mock balance: {balance} {token}")
        return balance

    async def get_transaction_status(self, tx_hash: str) -> str:
        await self._simulate_network()
        status = self._txs.get(tx_hash, "not_found")
        logger.debug(f"[WALLET] Mock tx {tx_hash[:16]}... status: {status}")
        return status

    async def get_wallet_address(self) -> str:
        return self._MOCK_ADDRESS


# ---------------------------------------------------------------------------
# WalletFactory
# ---------------------------------------------------------------------------

class WalletFactory:
    """Returns WDKWallet if WDK is fully configured, otherwise MockWallet."""

    @staticmethod
    def create() -> BaseWallet:
        wdk_ready = all([
            config.wdk_endpoint,
            config.wdk_api_key,
            config.wdk_wallet_address,
        ])
        if wdk_ready:
            logger.info("[WALLET] WDKWallet initialised — live transactions enabled")
            return WDKWallet()
        logger.warning(
            "[WALLET] WDK not fully configured — falling back to MockWallet. "
            "Set WDK_ENDPOINT, WDK_API_KEY, WDK_WALLET_ADDRESS in .env to enable live tips."
        )
        return MockWallet()


# ---------------------------------------------------------------------------
# Singleton used across the app
# ---------------------------------------------------------------------------

wallet: BaseWallet = WalletFactory.create()
