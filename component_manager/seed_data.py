"""Seed the Component Manager database with a starting catalog.

Run with:
    PYTHONPATH=. component_manager/.venv/bin/python -m component_manager.seed_data
"""

import asyncio

from component_manager import catalog
from component_manager.db import get_db, reset_db


async def seed() -> None:
    """Populate the shared component catalog and local inventory."""

    db = await get_db()

    for component_id, data in catalog.load_components().items():
        await db.upsert_component(
            component_id=component_id,
            name=data["display_name"],
            category=data["interface"],
            voltage=data["voltage"],
            interface=data["interface"],
            pin_count=len(data["signal_pins"]),
            description=", ".join(data.get("aliases", [])),
        )
        await db.upsert_inventory(component_id, catalog.seed_stock(component_id))
    component_count = len(catalog.load_components())
    print(f"Seeded {component_count} components and their local inventory.")


async def _seed_close() -> None:
    """Seed then close the connection so aiosqlite's worker thread lets the
    interpreter exit (it is not a daemon thread)."""

    await seed()
    await reset_db()


if __name__ == "__main__":
    asyncio.run(_seed_close())
