"""Shared test setup.

These are unit tests: nothing here should touch a database, Solr or Redis.
CKAN's database fixtures wipe whatever database is configured, and in a dev
container that is the dev database, so they are blocked here rather than
trusted to be left unused.
"""
import pytest


def _blocked(name):
    @pytest.fixture
    def fixture():
        pytest.fail(
            f"The {name} fixture resets a database or search index. These tests "
            "are unit tests and must not use it."
        )

    return fixture


reset_db = _blocked("reset_db")
clean_db = _blocked("clean_db")
reset_index = _blocked("reset_index")
clean_index = _blocked("clean_index")
clean_datastore = _blocked("clean_datastore")


@pytest.fixture
def spatialdata_config(monkeypatch):
    """The extension's settings dict, restored after each test."""
    from ckanext.spatialdata.config import config

    def set_(**values):
        for key, value in values.items():
            monkeypatch.setitem(config, key, value)
        return config

    return set_
