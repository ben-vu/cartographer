"""Clean and validate the loaded data with polars, emit a data-quality report,
and materialise an analysis-ready `orders_clean` table back into PostgreSQL.

We deliberately use polars here (the rest of the project uses pandas) to show
both engines and because polars' lazy API makes the validation pass cheap even
on the full 30M-row dataset.
"""
from __future__ import annotations

import io
import json
import logging

import polars as pl

import config
from src import db

log = logging.getLogger(__name__)


def _load_frames() -> dict[str, pl.DataFrame]:
    """Pull the raw tables from PostgreSQL into polars frames."""
    frames = {}
    for name, query in {
        "orders": "SELECT * FROM orders",
        "order_products": "SELECT * FROM order_products",
        "products": "SELECT * FROM products",
        "product_prices": "SELECT * FROM product_prices",
    }.items():
        frames[name] = pl.from_pandas(db.read_sql(query))
    return frames


def _quality_report(f: dict[str, pl.DataFrame]) -> dict:
    """Run referential/sanity checks and return a JSON-able report dict."""
    orders, op = f["orders"], f["order_products"]
    products, prices = f["products"], f["product_prices"]

    report: dict[str, object] = {}

    # Null counts per table.
    report["null_counts"] = {
        name: {c: int(df[c].null_count()) for c in df.columns}
        for name, df in f.items()
    }

    # Duplicate keys.
    report["duplicate_order_ids"] = int(orders.height - orders["order_id"].n_unique())
    report["duplicate_line_items"] = int(
        op.height - op.select(["order_id", "product_id"]).unique().height
    )

    # days_since_prior_order: nulls allowed only on a user's first order.
    first_orders = orders.filter(pl.col("order_number") == 1).height
    null_dspo = int(orders["days_since_prior_order"].null_count())
    report["dspo_nulls_match_first_orders"] = (null_dspo == first_orders)
    report["dspo_out_of_range"] = int(
        orders.filter(
            (pl.col("days_since_prior_order") < 0)
            | (pl.col("days_since_prior_order") > 30)
        ).height
    )

    # Referential integrity.
    prod_ids = set(products["product_id"].to_list())
    order_ids = set(orders["order_id"].to_list())
    report["orphan_product_refs"] = int(
        op.filter(~pl.col("product_id").is_in(prod_ids)).height
    )
    report["orphan_order_refs"] = int(
        op.filter(~pl.col("order_id").is_in(order_ids)).height
    )

    # Price sanity.
    report["nonpositive_prices"] = int(prices.filter(pl.col("price") <= 0).height)

    # Orders with no line items.
    orders_with_items = set(op["order_id"].to_list())
    report["orders_without_items"] = int(
        orders.filter(~pl.col("order_id").is_in(orders_with_items)).height
    )

    return report


def _build_orders_clean(f: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Per-order table enriched with basket_size and order_value (monetary)."""
    op = f["order_products"]
    prices = f["product_prices"]

    line_value = op.join(prices, on="product_id", how="left")
    per_order = line_value.group_by("order_id").agg(
        basket_size=pl.len(),
        order_value=pl.col("price").sum().round(2),
        reordered_items=pl.col("reordered").sum(),
    )
    clean = (
        f["orders"]
        .join(per_order, on="order_id", how="inner")
        # Cast/normalise types and clip the recency field defensively.
        .with_columns(
            pl.col("days_since_prior_order")
            .cast(pl.Float64)
            .clip(0, 30)
            .alias("days_since_prior_order")
        )
        .sort(["user_id", "order_number"])
    )
    return clean


def _write_clean(clean: pl.DataFrame) -> None:
    """COPY the clean per-order table back into PostgreSQL."""
    ddl = """
    DROP TABLE IF EXISTS orders_clean;
    CREATE TABLE orders_clean (
        order_id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        eval_set TEXT NOT NULL,
        order_number INTEGER,
        order_dow INTEGER,
        order_hour_of_day INTEGER,
        days_since_prior_order DOUBLE PRECISION,
        basket_size INTEGER,
        order_value NUMERIC(10,2),
        reordered_items INTEGER
    );
    """
    eng = db.get_engine()
    from sqlalchemy import text
    with eng.begin() as conn:
        for stmt in ddl.split(";"):
            if stmt.strip():
                conn.execute(text(stmt))

    cols = ["order_id", "user_id", "eval_set", "order_number", "order_dow",
            "order_hour_of_day", "days_since_prior_order", "basket_size",
            "order_value", "reordered_items"]
    buf = io.StringIO()
    clean.select(cols).write_csv(buf, include_header=False)
    buf.seek(0)
    raw = eng.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.copy_expert(
                f"COPY orders_clean ({', '.join(cols)}) "
                f"FROM STDIN WITH (FORMAT csv, NULL '')",
                buf,
            )
        raw.commit()
    finally:
        raw.close()
    log.info("Wrote %s rows -> orders_clean", f"{clean.height:,}")


def clean() -> dict:
    frames = _load_frames()
    report = _quality_report(frames)

    # Persist the report.
    report_path = config.OUTPUTS / "data_quality_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    log.info("Data-quality report -> %s", report_path)
    for k, v in report.items():
        if k != "null_counts":
            log.info("  %-32s %s", k, v)

    clean_df = _build_orders_clean(frames)
    _write_clean(clean_df)
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    clean()
