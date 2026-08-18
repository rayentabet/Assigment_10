"""Shared component identities and initial local inventory quantities.

Component identities are loaded from the same tools/data/components.json used
by the Wiring Agent (Assignment_10/tools/wiring_tools.py), so a component
named in a wiring plan and a component priced here always refer to the same
part.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPONENTS_CATALOG_PATH = REPO_ROOT / "tools" / "data" / "components.json"

STARTING_STOCK = {
    "hc-sr04": 12,
    "sg90": 8,
    "l298n": 5,
    "mpu6050": 4,
    "ssd1306": 3,
    "dc_motor": 6,
    "ir_sensor": 10,
    "ldr": 20,
    "button": 25,
    "led": 40,
    "sd_card_module": 2,
}
DEFAULT_STOCK = 5

def load_components() -> dict:
    """Return the shared component catalog keyed by component_id."""

    return json.loads(COMPONENTS_CATALOG_PATH.read_text())


def seed_stock(component_id: str) -> int:
    """Return the starting on-hand quantity for a newly seeded component."""

    return STARTING_STOCK.get(component_id, DEFAULT_STOCK)
