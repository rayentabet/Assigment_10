"""Deterministic board/component pin allocation and wiring validation."""

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

DATA_FOLDER = Path(__file__).parent / "data"
BOARDS: dict[str, Any] = json.loads((DATA_FOLDER / "boards.json").read_text())
COMPONENTS: dict[str, Any] = json.loads((DATA_FOLDER / "components.json").read_text())

SHARED_POWER_PINS = {"5V", "3V3", "VIN", "GND"}


def _normalize(name: str) -> str:
    """Turn free text into a lookup key."""

    return re.sub(r"[\s_-]+", " ", name.strip().lower())


def resolve_board(board: str) -> str | None:
    """Match free-text board names to a catalog key."""

    normalized = _normalize(board).replace(" ", "_")
    if normalized in BOARDS:
        return normalized
    for key, data in BOARDS.items():
        if _normalize(data["display_name"]) == _normalize(board):
            return key
    return None


def resolve_component(component: str) -> str | None:
    """Match free-text component names (or aliases) to a catalog key."""

    normalized = _normalize(component)
    if component in COMPONENTS:
        return component
    for key, data in COMPONENTS.items():
        candidates = [key, data["display_name"], *data.get("aliases", [])]
        if any(_normalize(candidate) == normalized for candidate in candidates):
            return key
    return None


@tool
def get_board(board: str) -> dict:
    """Return a board's digital, analog, PWM, UART, I2C, SPI, power, and reserved pins."""

    key = resolve_board(board)
    if key is None:
        return {
            "found": False,
            "error": f"Unknown board: {board}",
            "available_boards": sorted(BOARDS),
        }
    return {"found": True, "board": key, **BOARDS[key]}


@tool
def get_component(component: str) -> dict:
    """Return a component's voltage, interface, signal pins, and power pins."""

    key = resolve_component(component)
    if key is None:
        return {
            "found": False,
            "error": f"Unknown component: {component}",
            "available_components": sorted(COMPONENTS),
        }
    return {"found": True, "component": key, **COMPONENTS[key]}


def _take_pin(pool: list, used: set, avoid: set) -> Any | None:
    """Claim the first free pin, preferring pins outside the avoid set."""

    for pin in pool:
        if pin not in used and pin not in avoid:
            used.add(pin)
            return pin
    for pin in pool:
        if pin not in used:
            used.add(pin)
            return pin
    return None


def _power_pin(power_pins: list, voltage: float) -> str:
    """Pick the closest matching supply rail for a component's voltage."""

    if abs(voltage - 3.3) < abs(voltage - 5.0) and "3V3" in power_pins:
        return "3V3"
    if "5V" in power_pins:
        return "5V"
    return power_pins[0] if power_pins else "5V"


def _allocate_component(board: dict, component: dict, used: dict) -> tuple[dict | None, str | None]:
    """Assign real board pins to one component's signal and power pins."""

    interface = component["interface"]
    assigned: dict[str, Any] = {}
    reserved = {
        int(pin) if pin.lstrip("-").isdigit() else pin for pin in board.get("reserved_pins", {})
    }

    for pin_name in component["signal_pins"]:
        upper = pin_name.upper()
        if interface == "i2c" and upper == "SDA":
            assigned[pin_name] = board["i2c"]["sda"]
        elif interface == "i2c" and upper == "SCL":
            assigned[pin_name] = board["i2c"]["scl"]
        elif interface == "spi" and upper == "MOSI":
            assigned[pin_name] = board["spi"]["mosi"]
        elif interface == "spi" and upper == "MISO":
            assigned[pin_name] = board["spi"]["miso"]
        elif interface == "spi" and upper == "SCK":
            assigned[pin_name] = board["spi"]["sck"]
        elif interface == "pwm":
            pin = _take_pin(board["pwm_pins"], used["digital"], reserved)
            if pin is None:
                return None, f"No free PWM pin available for {pin_name}"
            assigned[pin_name] = pin
        elif interface == "analog":
            pin = _take_pin(board["analog_pins"], used["analog"], set())
            if pin is None:
                return None, f"No free analog pin available for {pin_name}"
            assigned[pin_name] = pin
        else:
            input_only = set(board.get("input_only_pins", []))
            pin = _take_pin(board["digital_pins"], used["digital"], reserved | input_only)
            if pin is None:
                return None, f"No free digital pin available for {pin_name}"
            assigned[pin_name] = pin

    for power_pin in component.get("power_pins_needed", []):
        upper = power_pin.upper()
        if upper == "GND":
            assigned[power_pin] = "GND"
        else:
            voltage = component.get("voltage", 5.0)
            assigned[power_pin] = _power_pin(board["power_pins"], voltage)

    return assigned, None


def _used_pins(board: dict, assignments: dict[str, dict]) -> dict[str, set]:
    """Build occupied-pin sets from a previously saved wiring plan."""

    shared_bus_values = {
        board["i2c"]["sda"],
        board["i2c"]["scl"],
        board["spi"]["mosi"],
        board["spi"]["miso"],
        board["spi"]["sck"],
    }
    used: dict[str, set] = {"digital": set(), "analog": set()}
    for assignment in assignments.values():
        for pin in assignment.values():
            if pin in SHARED_POWER_PINS or pin in shared_bus_values:
                continue
            if pin in board["analog_pins"] and pin not in board["digital_pins"]:
                used["analog"].add(pin)
            else:
                used["digital"].add(pin)
    return used


def _allocate_pins(
    board: str,
    components: list[str],
    existing_assignments: dict[str, dict] | None = None,
) -> dict:
    """Assign pins while preserving exclusive pins occupied by existing wiring.

    Args:
        board: Board identifier or display name.
        components: New components to add to the wiring plan.
        existing_assignments: Previously saved component-to-pin assignments for this
            thread. Pass an empty object only for a new design or explicit redesign.
    """

    board_key = resolve_board(board)
    if board_key is None:
        return {
            "success": False,
            "error": f"Unknown board: {board}",
            "available_boards": sorted(BOARDS),
        }
    board_data = BOARDS[board_key]

    assignments = {key: dict(value) for key, value in (existing_assignments or {}).items()}
    used = _used_pins(board_data, assignments)
    unallocated: list[dict] = []

    for raw_name in components:
        component_key = resolve_component(raw_name)
        if component_key is None:
            unallocated.append({"component": raw_name, "reason": "Unknown component"})
            continue
        component_data = COMPONENTS[component_key]
        assigned, error = _allocate_component(board_data, component_data, used)
        if error is not None:
            unallocated.append({"component": component_key, "reason": error})
            continue
        assignments[component_key] = assigned

    return {
        "success": not unallocated,
        "board": board_key,
        "assignments": assignments,
        "unallocated": unallocated,
    }


def make_allocator(existing_assignments: dict[str, dict] | None = None):
    """Create an allocation tool with thread-owned assignments injected privately."""

    preserved = {key: dict(value) for key, value in (existing_assignments or {}).items()}

    @tool("allocate_pins")
    def bound_allocator(board: str, components: list[str]) -> dict:
        """Add components without reusing exclusive pins occupied by saved wiring.

        Args:
            board: Board identifier or display name.
            components: New components to add to the current design.
        """

        return _allocate_pins(board, components, preserved)

    return bound_allocator


# A stateless allocator remains importable for direct tests and new designs. The
# Wiring Agent uses make_allocator() so existing assignments are not model-controlled.
allocate_pins = make_allocator()


@tool
def validate_wiring(board: str, pin_assignments: dict) -> dict:
    """Detect pin conflicts, missing power/ground, and voltage mismatches."""

    board_key = resolve_board(board)
    if board_key is None:
        return {
            "valid": False,
            "conflicts": [f"Unknown board: {board}"],
            "warnings": [],
        }
    board_data = BOARDS[board_key]

    shared_bus_values = {
        board_data["i2c"]["sda"],
        board_data["i2c"]["scl"],
        board_data["spi"]["mosi"],
        board_data["spi"]["miso"],
        board_data["spi"]["sck"],
    }
    all_board_pins = {
        *board_data["digital_pins"],
        *board_data["pwm_pins"],
        *board_data["analog_pins"],
        *shared_bus_values,
    }
    reserved = board_data.get("reserved_pins", {})

    pin_usage: dict[Any, list[str]] = {}
    conflicts: list[str] = []
    warnings: list[str] = []

    for component_key, assignment in pin_assignments.items():
        component_data = COMPONENTS.get(component_key)
        if component_data is None:
            warnings.append(f"{component_key}: unknown component, skipping voltage/power checks")

        has_ground = False
        for pin_name, pin_value in assignment.items():
            if pin_value in SHARED_POWER_PINS:
                if pin_value == "GND":
                    has_ground = True
                continue
            if pin_value not in all_board_pins:
                conflicts.append(
                    f"{component_key}.{pin_name}: pin {pin_value} does not exist on {board_key}"
                )
                continue
            if pin_value in shared_bus_values:
                continue
            pin_usage.setdefault(pin_value, []).append(f"{component_key}.{pin_name}")
            reserved_key = str(pin_value)
            if reserved_key in reserved:
                warnings.append(
                    f"{component_key}.{pin_name}: pin {pin_value} is reserved "
                    f"({reserved[reserved_key]})"
                )

        if component_data is not None:
            if component_data.get("power_pins_needed") and not has_ground:
                conflicts.append(f"{component_key}: missing a GND connection")
            voltage = component_data.get("voltage", board_data["logic_voltage"])
            if abs(voltage - board_data["logic_voltage"]) > 0.5:
                warnings.append(
                    f"{component_key} operates at {voltage}V but {board_key} logic is "
                    f"{board_data['logic_voltage']}V; use a level shifter or divider"
                )

    for pin_value, users in pin_usage.items():
        if len(users) > 1:
            conflicts.append(f"Pin {pin_value} is assigned to multiple signals: {', '.join(users)}")

    return {"valid": not conflicts, "conflicts": conflicts, "warnings": warnings}


@tool
def format_wiring_plan(board: str, pin_assignments: dict, validation: dict) -> dict:
    """Produce a structured wiring plan and a readable markdown table."""

    board_key = resolve_board(board) or board
    rows = ["| Component | Pin | Board Pin |", "|---|---|---|"]
    components_out = []

    for component_key, assignment in pin_assignments.items():
        display_name = COMPONENTS.get(component_key, {}).get("display_name", component_key)
        for pin_name, pin_value in assignment.items():
            rows.append(f"| {display_name} | {pin_name} | {pin_value} |")
        components_out.append(
            {"component": component_key, "display_name": display_name, "pins": assignment}
        )

    table_markdown = "\n".join(rows)
    if validation.get("conflicts"):
        conflict_lines = "\n".join(f"- {c}" for c in validation["conflicts"])
        table_markdown += f"\n\n**Conflicts:**\n{conflict_lines}"
    if validation.get("warnings"):
        warning_lines = "\n".join(f"- {w}" for w in validation["warnings"])
        table_markdown += f"\n\n**Warnings:**\n{warning_lines}"

    return {
        "board": board_key,
        "valid": validation.get("valid", False),
        "assignments": pin_assignments,
        "components": components_out,
        "conflicts": validation.get("conflicts", []),
        "warnings": validation.get("warnings", []),
        "table_markdown": table_markdown,
    }
