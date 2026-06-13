"""Central configuration for the Instacart RFM + Reorder project.

All tunables live here so the pipeline scripts stay clean. Database
credentials are read from environment variables (see .env.example), with
sensible local-development defaults.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv is optional at runtime
    pass

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent
DATA_RAW = ROOT / "data" / "raw"
OUTPUTS = ROOT / "outputs"
FIGURES = OUTPUTS / "figures"
TABLEAU = OUTPUTS / "tableau"
SQL_DIR = ROOT / "sql"

for _p in (DATA_RAW, OUTPUTS, FIGURES, TABLEAU):
    _p.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------- #
# Database (PostgreSQL)
# --------------------------------------------------------------------------- #
DB = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": os.getenv("PGPORT", "5432"),
    "user": os.getenv("PGUSER", "analytics"),
    "password": os.getenv("PGPASSWORD", "analytics"),
    "dbname": os.getenv("PGDATABASE", "instacart"),
}


def sqlalchemy_url() -> str:
    """Return a SQLAlchemy connection URL built from the DB config."""
    return (
        f"postgresql+psycopg2://{DB['user']}:{DB['password']}"
        f"@{DB['host']}:{DB['port']}/{DB['dbname']}"
    )


# --------------------------------------------------------------------------- #
# Synthetic-data generator settings (ignored when you bring real Kaggle CSVs)
# --------------------------------------------------------------------------- #
SAMPLE = {
    "seed": 42,
    "n_users": 5000,
    "n_products": 1000,
    "mean_orders_per_user": 12,   # Poisson lambda
    "min_orders_per_user": 3,
    "mean_basket_size": 8,        # Poisson lambda
}

# RFM scoring uses quintiles (5 bands) by default.
RFM_BANDS = 5

# Reorder model
MODEL = {
    "test_size": 0.25,
    "random_state": 42,
}
