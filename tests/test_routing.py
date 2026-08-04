from app.graph import SAFE_FALLBACK_ROUTE, VALID_ROUTES, validate_route


def test_known_routes_are_preserved() -> None:
    for route in VALID_ROUTES:
        assert validate_route(route) == route


def test_unknown_route_falls_back_safely() -> None:
    assert validate_route("invented_agent") == SAFE_FALLBACK_ROUTE
