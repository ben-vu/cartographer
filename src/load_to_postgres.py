"""Load the raw CSVs (synthetic or real Kaggle) into PostgreSQL.

Strategy
--------
* Apply sql/01_schema.sql (drops + recreates the tables).
* Bulk-load each catalog/orders file with COPY (orders of magnitude faster
  than INSERT, and it scales to the full 30M-row real dataset).
* The two Kaggle line-item files (prior, train) are unioned into a single
  `order_products` table with an eval_set discriminator.
* If product_prices.csv is absent (i.e. you brought the real dataset, which
  ships no prices), synthesise a deterministic price per product so that the
  Monetary dimension of RFM still works. See README.
* Finally apply sql/02_analytics_views.sql.
"""
from __future__ import annotations

import io
import logging

import numpy as np
import pandas as pd

import config
from src import db

log = logging.getLogger(__name__)


def _copy_df(df: pd.DataFrame, table: str, columns: list[str]) -> None:
    """COPY a DataFrame into `table` using a fast in-memory CSV stream."""
    buf = io.StringIO()
    df[columns].to_csv(buf, index=False, header=False, na_rep="")
    buf.seek(0)
    raw = db.get_engine().raw_connection()
    try:
        with raw.cursor() as cur:
            cur.copy_expert(
                f"COPY {table} ({', '.join(columns)}) "
                f"FROM STDIN WITH (FORMAT csv, NULL '')",
                buf,
            )
        raw.commit()
    finally:
        raw.close()
    log.info("Loaded %s rows -> %s", f"{len(df):,}", table)


def _ensure_prices(products: pd.DataFrame) -> pd.DataFrame:
    """Return a product_prices frame, generating one if the CSV is missing."""
    path = config.DATA_RAW / "product_prices.csv"
    if path.exists():
        return pd.read_csv(path)
    log.warning("product_prices.csv not found -> generating deterministic prices")
    rng = np.random.default_rng(config.SAMPLE["seed"])
    # Department-tier multiplier keeps generated prices plausible even on the
    # real catalog where we only know department_id.
    base = 2.0 + (products["department_id"].to_numpy() % 7)
    noise = rng.uniform(0.5, 4.0, size=len(products))
    price = np.round(np.floor(base * noise) + 0.99, 2)
    return pd.DataFrame({"product_id": products["product_id"], "price": price})


def load() -> None:
    raw = config.DATA_RAW
    log.info("Applying schema (sql/01_schema.sql)...")
    db.run_sql_file(config.SQL_DIR / "01_schema.sql")

    # --- catalog ---------------------------------------------------------- #
    departments = pd.read_csv(raw / "departments.csv")
    aisles = pd.read_csv(raw / "aisles.csv")
    products = pd.read_csv(raw / "products.csv")
    prices = _ensure_prices(products)

    _copy_df(departments, "departments", ["department_id", "department"])
    # Real aisles.csv has no department_id column; tolerate either shape.
    _copy_df(aisles, "aisles", ["aisle_id", "aisle"])
    _copy_df(products, "products",
             ["product_id", "product_name", "aisle_id", "department_id"])
    _copy_df(prices, "product_prices", ["product_id", "price"])

    # --- orders ----------------------------------------------------------- #
    orders = pd.read_csv(raw / "orders.csv")
    _copy_df(
        orders, "orders",
        ["order_id", "user_id", "eval_set", "order_number",
         "order_dow", "order_hour_of_day", "days_since_prior_order"],
    )

    # --- line items: union prior + train --------------------------------- #
    op_prior = pd.read_csv(raw / "order_products__prior.csv")
    op_prior["eval_set"] = "prior"
    op_train = pd.read_csv(raw / "order_products__train.csv")
    op_train["eval_set"] = "train"
    order_products = pd.concat([op_prior, op_train], ignore_index=True)
    _copy_df(
        order_products, "order_products",
        ["order_id", "product_id", "add_to_cart_order", "reordered", "eval_set"],
    )

    log.info("Applying analytics views (sql/02_analytics_views.sql)...")
    db.run_sql_file(config.SQL_DIR / "02_analytics_views.sql")

    counts = db.read_sql(
        "SELECT 'orders' t, count(*) n FROM orders "
        "UNION ALL SELECT 'order_products', count(*) FROM order_products "
        "UNION ALL SELECT 'products', count(*) FROM products"
    )
    log.info("Row counts:\n%s", counts.to_string(index=False))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not db.ping():
        raise SystemExit(
            "PostgreSQL is not reachable. Check your .env / that the server is up."
        )
    load()
