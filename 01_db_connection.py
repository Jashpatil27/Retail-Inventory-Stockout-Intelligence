"""
FILE: 01_db_connection.py
PROJECT: Retail Inventory & Stockout Intelligence
PURPOSE: Central place to connect Python to PostgreSQL. Every other script
         imports get_engine() / get_connection() from here instead of
         repeating connection code.

SETUP:
1. pip install sqlalchemy psycopg2-binary pandas python-dotenv
2. Create a .env file in the project root with:
       DB_HOST=localhost
       DB_PORT=5432
       DB_NAME=retail_inventory
       DB_USER=postgres
       DB_PASSWORD=your_password
3. Never hardcode credentials in the script itself or commit .env to GitHub.
"""

import os
from urllib.parse import quote_plus
from sqlalchemy import create_engine
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "retail_inventory")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")


def get_engine():
    """
    Returns a SQLAlchemy engine connected to the PostgreSQL database.
    Use this with pandas: pd.read_sql(query, engine) or df.to_sql(...).
    """
    # quote_plus escapes special characters (like @, #, /) so a password
    # containing them doesn't break the connection string's structure.
    safe_password = quote_plus(DB_PASSWORD)
    connection_string = (
        f"postgresql+psycopg2://{DB_USER}:{safe_password}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    engine = create_engine(connection_string)
    return engine


def test_connection():
    """Quick sanity check that the DB connection works."""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            print("Connected successfully to:", DB_NAME)
    except Exception as e:
        print("Connection failed:", e)


if __name__ == "__main__":
    test_connection()
