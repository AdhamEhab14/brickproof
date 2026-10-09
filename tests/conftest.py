def pytest_collection_modifyitems(config, items):
    """Renode tests are slow: run them only when asked for with -m renode."""
    if "renode" in (config.getoption("markexpr") or ""):
        return
    import pytest
    skip = pytest.mark.skip(reason="slow; run with -m renode")
    for item in items:
        if "renode" in item.keywords:
            item.add_marker(skip)
