import pytest

from component_manager import tools


@pytest.mark.asyncio
async def test_check_component_availability_known_component() -> None:
    result = await tools.check_component_availability("hc-sr04")

    assert result["found"] is True
    assert result["quantity_on_hand"] > 0
    assert result["quantity_available"] == result["quantity_on_hand"] - result["quantity_reserved"]


@pytest.mark.asyncio
async def test_check_component_availability_unknown_component() -> None:
    result = await tools.check_component_availability("flux-capacitor")

    assert result["found"] is False

