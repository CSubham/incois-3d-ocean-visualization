"""Pytest configuration for ingestion integration proofs."""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: requires explicitly configured local services and/or sources",
    )
