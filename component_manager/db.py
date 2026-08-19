"""SQLite persistence for inventory, DigiKey OAuth, proposals, and orders."""

import asyncio
from pathlib import Path
from typing import Any

import aiosqlite

from component_manager.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_states (
    state_hash TEXT PRIMARY KEY,
    expires_at INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider TEXT PRIMARY KEY,
    encrypted_payload BLOB NOT NULL,
    expires_at INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS digikey_proposals (
    proposal_id TEXT PRIMARY KEY,
    part_number TEXT NOT NULL,
    manufacturer_part_number TEXT,
    component_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    total REAL NOT NULL,
    currency TEXT NOT NULL,
    product_url TEXT,
    image_url TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    approval_token TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    mandate_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS digikey_orders (
    order_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    sales_order_id TEXT,
    status TEXT NOT NULL,
    mandate_json TEXT NOT NULL,
    response_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (proposal_id) REFERENCES digikey_proposals(proposal_id)
);
"""


class ComponentDB:
    """Async SQLite access for the Component Manager's own data."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.database_path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("Database is not connected.")
        return self._connection

    async def _fetch_one(self, query: str, params: tuple = ()) -> dict | None:
        cursor = await self.connection.execute(query, params)
        row = await cursor.fetchone()
        await cursor.close()
        return dict(row) if row is not None else None

    async def _fetch_all(self, query: str, params: tuple = ()) -> list[dict]:
        cursor = await self.connection.execute(query, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(row) for row in rows]

    # -- OAuth ---------------------------------------------------------------

    async def save_oauth_state(self, state_hash: str, expires_at: int) -> None:
        await self.connection.execute(
            "DELETE FROM oauth_states WHERE expires_at < ?", (expires_at - 600,)
        )
        await self.connection.execute(
            "INSERT OR REPLACE INTO oauth_states (state_hash, expires_at) VALUES (?, ?)",
            (state_hash, expires_at),
        )
        await self.connection.commit()

    async def consume_oauth_state(self, state_hash: str, now: int) -> bool:
        row = await self._fetch_one(
            "SELECT state_hash FROM oauth_states WHERE state_hash = ? AND expires_at >= ?",
            (state_hash, now),
        )
        await self.connection.execute(
            "DELETE FROM oauth_states WHERE state_hash = ?", (state_hash,)
        )
        await self.connection.commit()
        return row is not None

    async def save_oauth_tokens(
        self, provider: str, encrypted_payload: bytes, expires_at: int
    ) -> None:
        await self.connection.execute(
            """
            INSERT INTO oauth_tokens (provider, encrypted_payload, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
                encrypted_payload = excluded.encrypted_payload,
                expires_at = excluded.expires_at,
                updated_at = CURRENT_TIMESTAMP
            """,
            (provider, encrypted_payload, expires_at),
        )
        await self.connection.commit()

    async def get_oauth_tokens(self, provider: str) -> dict | None:
        return await self._fetch_one(
            "SELECT encrypted_payload, expires_at, updated_at FROM oauth_tokens WHERE provider = ?",
            (provider,),
        )

    async def delete_oauth_tokens(self, provider: str) -> None:
        await self.connection.execute("DELETE FROM oauth_tokens WHERE provider = ?", (provider,))
        await self.connection.commit()

    # -- DigiKey sandbox purchasing ------------------------------------------

    async def insert_digikey_proposal(self, **fields: Any) -> None:
        await self.connection.execute(
            """
            INSERT INTO digikey_proposals (
                proposal_id, part_number, manufacturer_part_number, component_name,
                quantity, unit_price, total, currency, product_url, image_url,
                status, approval_token, expires_at, mandate_json
            ) VALUES (
                :proposal_id, :part_number, :manufacturer_part_number, :component_name,
                :quantity, :unit_price, :total, :currency, :product_url, :image_url,
                :status, :approval_token, :expires_at, :mandate_json
            )
            """,
            fields,
        )
        await self.connection.commit()

    async def get_digikey_proposal(self, proposal_id: str) -> dict | None:
        return await self._fetch_one(
            "SELECT * FROM digikey_proposals WHERE proposal_id = ?", (proposal_id,)
        )

    async def update_digikey_proposal(self, proposal_id: str, status: str) -> None:
        await self.connection.execute(
            "UPDATE digikey_proposals SET status = ? WHERE proposal_id = ?",
            (status, proposal_id),
        )
        await self.connection.commit()

    async def get_digikey_order_by_key(self, idempotency_key: str) -> dict | None:
        return await self._fetch_one(
            "SELECT * FROM digikey_orders WHERE idempotency_key = ?", (idempotency_key,)
        )

    async def get_digikey_order(self, order_id: str) -> dict | None:
        return await self._fetch_one(
            "SELECT * FROM digikey_orders WHERE order_id = ?", (order_id,)
        )

    async def insert_digikey_order(self, **fields: Any) -> None:
        await self.connection.execute(
            """
            INSERT INTO digikey_orders (
                order_id, proposal_id, idempotency_key, sales_order_id,
                status, mandate_json, response_json
            ) VALUES (
                :order_id, :proposal_id, :idempotency_key, :sales_order_id,
                :status, :mandate_json, :response_json
            )
            """,
            fields,
        )
        await self.connection.commit()

    async def update_digikey_order(
        self, order_id: str, status: str, sales_order_id: str | None, response_json: str
    ) -> None:
        await self.connection.execute(
            """
            UPDATE digikey_orders
            SET status = ?, sales_order_id = ?, response_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE order_id = ?
            """,
            (status, sales_order_id, response_json, order_id),
        )
        await self.connection.commit()


_db: ComponentDB | None = None
_lock = asyncio.Lock()


async def get_db() -> ComponentDB:
    """Open (once) and reuse the process-wide database connection."""

    global _db
    if _db is not None:
        return _db
    async with _lock:
        if _db is not None:
            return _db
        database = ComponentDB(settings.database_path)
        await database.connect()
        _db = database
        return database


async def reset_db() -> None:
    """Force re-initialization from the current settings; used by tests."""

    global _db
    if _db is not None:
        await _db.close()
    _db = None
