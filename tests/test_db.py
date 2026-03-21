import pytest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.pool import init_pool, db_pool, get_cursor, PLACEHOLDER


@pytest.fixture(scope="module")
def db_connection():
    """Initialize DB connection for tests"""
    init_pool()
    yield
    if db_pool:
        db_pool.putconn(db_pool.getconn())


def test_db_pool_initialized(db_pool):
    """Test that DB pool is initialized"""
    assert db_pool is not None


def test_placeholder_defined():
    """Test that PLACEHOLDER is defined"""
    assert PLACEHOLDER == "%s"


def test_cursor_context_manager(db_connection):
    """Test that cursor context manager works"""
    with get_cursor() as cur:
        cur.execute("SELECT 1 as test")
        result = cur.fetchone()
        assert result["test"] == 1
