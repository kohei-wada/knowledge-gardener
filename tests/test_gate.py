from recap.autorecap.gate import is_substantive


def test_durable_change_is_always_substantive():
    assert is_substantive(True, entry_count=1, duration_min=0, env={}) is True


def test_below_floor_readonly_is_not_substantive():
    assert is_substantive(False, entry_count=2, duration_min=1, env={}) is False


def test_at_call_floor_is_substantive():
    assert is_substantive(False, entry_count=5, duration_min=0, env={}) is True


def test_at_minute_floor_is_substantive():
    assert is_substantive(False, entry_count=1, duration_min=5, env={}) is True


def test_env_override_raises_floor():
    env = {"KG_RECAP_MIN_CALLS": "20", "KG_RECAP_MIN_MINUTES": "30"}
    assert is_substantive(False, entry_count=5, duration_min=5, env=env) is False
    assert is_substantive(False, entry_count=20, duration_min=0, env=env) is True
