"""
Database connection and session utilities for RoleRadar API using psycopg2.
"""

from contextlib import contextmanager
import os
from typing import Generator
import psycopg2


def get_db_connection():
    """
    Connects to the PostgreSQL database using environment variables or standard defaults.
    Supports DATABASE_URL for hosted providers, with fallback to local defaults.
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    dbname = os.getenv("PGDATABASE", "roleradar")
    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")
    host = os.getenv("PGHOST")
    port = os.getenv("PGPORT")

    conn_params = {"dbname": dbname}
    if user:
        conn_params["user"] = user
    if password:
        conn_params["password"] = password
    if host:
        conn_params["host"] = host
    if port:
        conn_params["port"] = port

    return psycopg2.connect(**conn_params)


@contextmanager
def get_db_cursor() -> Generator:
    """
    Context manager providing a database cursor with automatic cleanup.
    Ensures both cursor and connection are closed safely.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()
