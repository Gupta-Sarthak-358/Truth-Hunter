from contextlib import contextmanager
import logging
import os

from psycopg2 import InterfaceError, OperationalError
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool

PLACEHOLDER = "%s"

logger = logging.getLogger(__name__)

db_pool = None  # type: ignore[assignment]


def _safe_close_cursor(cursor):
    try:
        cursor.close()
    except Exception:
        logger.debug("Cursor close failed", exc_info=True)


def _safe_discard_connection(conn):
    if db_pool is None:
        return
    try:
        db_pool.putconn(conn, close=True)
    except Exception:
        logger.warning("Failed to discard DB connection", exc_info=True)


def _safe_return_connection(conn):
    if db_pool is None:
        return
    try:
        db_pool.putconn(conn)
    except Exception:
        logger.warning("Failed to return DB connection to pool", exc_info=True)


def init_pool():
    global db_pool
    db_pool = SimpleConnectionPool(
        minconn=1, maxconn=10, dsn=os.environ.get("DATABASE_URL")
    )
    logger.info("DB connection pool initialized (1-10 connections)")

    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SET statement_timeout = 5000")
        conn.commit()
        _safe_close_cursor(cur)
        logger.info("Statement timeout set to 5000ms")
    except Exception:
        _safe_discard_connection(conn)
        raise
    finally:
        if not getattr(conn, "closed", 1):
            _safe_return_connection(conn)


@contextmanager
def get_cursor():
    if db_pool is None:
        raise RuntimeError("Database pool not initialized. Call init_pool() first.")

    conn = db_pool.getconn()
    cursor = None
    should_return_conn = True

    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SET statement_timeout = 5000")
        yield cursor
        conn.commit()
        logger.debug("DB transaction committed")
    except Exception:
        try:
            if not getattr(conn, "closed", 1):
                conn.rollback()
                logger.exception("DB transaction rolled back")
            else:
                logger.exception("DB transaction failed after connection closed")
        except (InterfaceError, OperationalError):
            logger.exception("DB rollback failed because connection is no longer usable")

        _safe_discard_connection(conn)
        should_return_conn = False
        raise
    finally:
        if cursor is not None:
            _safe_close_cursor(cursor)
        if should_return_conn and not getattr(conn, "closed", 1):
            _safe_return_connection(conn)
            logger.debug("DB connection returned to pool")


def get_db():
    if db_pool is None:
        raise RuntimeError("Database pool not initialized")
    return db_pool.getconn()


def get_cur(conn):
    return conn.cursor(cursor_factory=RealDictCursor)


def db_close(cur, conn):
    _safe_close_cursor(cur)
    try:
        if not getattr(conn, "closed", 1):
            conn.commit()
    except Exception:
        try:
            if not getattr(conn, "closed", 1):
                conn.rollback()
        except Exception:
            logger.exception("Deprecated db_close rollback failed")
        _safe_discard_connection(conn)
        return

    if not getattr(conn, "closed", 1):
        _safe_return_connection(conn)
