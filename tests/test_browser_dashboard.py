import pytest

from browser_dashboard.main import _connect, _discovery


def test_dashboard_discovery_requires_two_consecutive_closes():
    assert _discovery([{"close_value": 60500}], 60000, 59000) == "DISCOVERY_CANDIDATE_ABOVE"
    assert _discovery([{"close_value": 60500}, {"close_value": 60600}], 60000, 59000) == "DISCOVERY_ABOVE"
    assert _discovery([{"close_value": 58000}, {"close_value": 59500}], 60000, 59000) == "IN_VALUE"


def test_dashboard_discovery_does_not_treat_equal_boundary_as_outside():
    assert _discovery([{"close_value": 60000}], 60000, 59000) == "IN_VALUE"
    assert _discovery([{"close_value": 59000}], 60000, 59000) == "IN_VALUE"


def test_dashboard_refuses_non_production_host_before_connecting(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://amt_dashboard_ro:secret@ep-old-bar-aoau4qop.c-2.ap-southeast-1.aws.neon.tech/amt_research",
    )
    with pytest.raises(RuntimeError, match="production amt_dashboard_ro"):
        _connect()
