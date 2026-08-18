from tools import wiring_tools


def test_get_board_known_board() -> None:
    result = wiring_tools.get_board.invoke({"board": "Arduino Uno"})

    assert result["found"] is True
    assert result["board"] == "arduino_uno"
    assert 13 in result["digital_pins"]


def test_get_board_unknown_board() -> None:
    result = wiring_tools.get_board.invoke({"board": "raspberry pi"})

    assert result["found"] is False
    assert "arduino_uno" in result["available_boards"]


def test_get_component_resolves_alias() -> None:
    result = wiring_tools.get_component.invoke({"component": "ultrasonic sensor"})

    assert result["found"] is True
    assert result["component"] == "hc-sr04"


def test_get_component_unknown_component() -> None:
    result = wiring_tools.get_component.invoke({"component": "flux capacitor"})

    assert result["found"] is False


def test_allocate_pins_assigns_distinct_digital_pins() -> None:
    result = wiring_tools.allocate_pins.invoke(
        {"board": "arduino_uno", "components": ["hc-sr04", "button"]}
    )

    assert result["success"] is True
    power_pins = {"5V", "3V3", "VIN", "GND"}
    trig_echo = set(result["assignments"]["hc-sr04"].values()) - power_pins
    button_pin = {pin for pin in result["assignments"]["button"].values() if pin not in power_pins}
    assert not trig_echo & button_pin


def test_allocate_pins_shares_i2c_bus() -> None:
    result = wiring_tools.allocate_pins.invoke(
        {"board": "arduino_uno", "components": ["mpu6050", "ssd1306"]}
    )

    assert result["assignments"]["mpu6050"]["SDA"] == result["assignments"]["ssd1306"]["SDA"]
    assert result["assignments"]["mpu6050"]["SCL"] == result["assignments"]["ssd1306"]["SCL"]


def test_allocate_pins_reports_unknown_component() -> None:
    result = wiring_tools.allocate_pins.invoke(
        {"board": "arduino_uno", "components": ["hc-sr04", "flux capacitor"]}
    )

    assert result["success"] is False
    assert result["unallocated"][0]["component"] == "flux capacitor"


def test_allocate_pins_unknown_board() -> None:
    result = wiring_tools.allocate_pins.invoke({"board": "raspberry pi", "components": []})

    assert result["success"] is False


def test_allocate_pins_preserves_existing_pins() -> None:
    existing = {"button": {"SIGNAL": 2, "GND": "GND"}}
    allocator = wiring_tools.make_allocator(existing)

    result = allocator.invoke(
        {
            "board": "arduino_uno",
            "components": ["hc-sr04"],
        }
    )

    assert result["assignments"]["button"]["SIGNAL"] == 2
    assert 2 not in {
        result["assignments"]["hc-sr04"]["TRIG"],
        result["assignments"]["hc-sr04"]["ECHO"],
    }
    assert "existing_assignments" not in allocator.args


def test_validate_wiring_detects_pin_conflict() -> None:
    validation = wiring_tools.validate_wiring.invoke(
        {
            "board": "arduino_uno",
            "pin_assignments": {
                "hc-sr04": {"TRIG": 7, "ECHO": 8, "VCC": "5V", "GND": "GND"},
                "button": {"SIGNAL": 7, "GND": "GND"},
            },
        }
    )

    assert validation["valid"] is False
    assert any("Pin 7" in conflict for conflict in validation["conflicts"])


def test_validate_wiring_does_not_flag_shared_i2c_bus() -> None:
    allocation = wiring_tools.allocate_pins.invoke(
        {"board": "arduino_uno", "components": ["mpu6050", "ssd1306"]}
    )
    validation = wiring_tools.validate_wiring.invoke(
        {"board": "arduino_uno", "pin_assignments": allocation["assignments"]}
    )

    assert validation["valid"] is True
    assert validation["conflicts"] == []


def test_validate_wiring_flags_missing_ground() -> None:
    validation = wiring_tools.validate_wiring.invoke(
        {
            "board": "arduino_uno",
            "pin_assignments": {"hc-sr04": {"TRIG": 7, "ECHO": 8, "VCC": "5V"}},
        }
    )

    assert validation["valid"] is False
    assert any("GND" in conflict for conflict in validation["conflicts"])


def test_validate_wiring_warns_on_voltage_mismatch() -> None:
    validation = wiring_tools.validate_wiring.invoke(
        {
            "board": "esp32",
            "pin_assignments": {"hc-sr04": {"TRIG": 4, "ECHO": 5, "VCC": "5V", "GND": "GND"}},
        }
    )

    assert any("3.3V" in warning for warning in validation["warnings"])


def test_format_wiring_plan_builds_table() -> None:
    allocation = wiring_tools.allocate_pins.invoke(
        {"board": "arduino_uno", "components": ["hc-sr04"]}
    )
    validation = wiring_tools.validate_wiring.invoke(
        {"board": "arduino_uno", "pin_assignments": allocation["assignments"]}
    )
    plan = wiring_tools.format_wiring_plan.invoke(
        {
            "board": "arduino_uno",
            "pin_assignments": allocation["assignments"],
            "validation": validation,
        }
    )

    assert plan["board"] == "arduino_uno"
    assert plan["valid"] is True
    assert plan["assignments"] == allocation["assignments"]
    assert "HC-SR04" in plan["table_markdown"]
