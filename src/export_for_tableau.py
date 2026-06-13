"""Produce the analysis-ready CSV extracts that the Tableau workbook connects to.

One tidy file per grain keeps the Tableau data model simple. Everything is
aggregated in PostgreSQL so the workbook stays fast even on the full dataset.
Outputs land in outputs/tableau/ (rfm_segments.csv and reorder_predictions.csv
are written by the RFM and model steps; this module adds the rest).
"""
from __future__ import annotations

import logging

import config
from src import db

log = logging.getLogger(__name__)


def export() -> None:
    out = config.TABLEAU

    # 1) Segment summary (Page 1 - Customer Segmentation).
    segment_summary = db.read_sql(
        """
        SELECT segment,
               COUNT(*)                                  AS customers,
               ROUND(AVG(recency)::numeric, 1)           AS avg_recency_days,
               ROUND(AVG(frequency)::numeric, 1)         AS avg_frequency,
               ROUND(AVG(monetary)::numeric, 2)          AS avg_monetary,
               ROUND(SUM(monetary)::numeric, 2)          AS total_monetary,
               ROUND(AVG(rfm_score)::numeric, 2)         AS avg_rfm_score,
               MAX(action)                               AS recommended_action
        FROM rfm_segments
        GROUP BY segment
        ORDER BY total_monetary DESC
        """
    )
    segment_summary["pct_customers"] = (
        100 * segment_summary["customers"] / segment_summary["customers"].sum()
    ).round(1)
    segment_summary["pct_revenue"] = (
        100 * segment_summary["total_monetary"]
        / segment_summary["total_monetary"].sum()
    ).round(1)
    segment_summary.to_csv(out / "segment_summary.csv", index=False)
    log.info("Exported segment_summary.csv (%s segments)", len(segment_summary))

    # 2) Department loyalty (Page 2 - Category Loyalty).
    department_loyalty = db.read_sql(
        """
        SELECT department,
               line_items,
               reordered_items,
               reorder_rate,
               unique_customers
        FROM v_department_loyalty
        ORDER BY reorder_rate DESC
        """
    )
    department_loyalty.to_csv(out / "department_loyalty.csv", index=False)
    log.info("Exported department_loyalty.csv (%s departments)",
             len(department_loyalty))

    # 3) Top products by loyalty (Page 2 - drill-down).
    product_loyalty = db.read_sql(
        """
        SELECT p.product_id,
               p.product_name,
               d.department,
               COUNT(*)                          AS times_purchased,
               ROUND(AVG(op.reordered::numeric), 4) AS reorder_rate,
               COUNT(DISTINCT o.user_id)         AS unique_customers
        FROM order_products op
        JOIN orders o   ON o.order_id = op.order_id
        JOIN products p ON p.product_id = op.product_id
        JOIN departments d ON d.department_id = p.department_id
        WHERE op.eval_set = 'prior'
        GROUP BY p.product_id, p.product_name, d.department
        HAVING COUNT(*) >= 20
        ORDER BY reorder_rate DESC, times_purchased DESC
        LIMIT 200
        """
    )
    product_loyalty.to_csv(out / "product_loyalty.csv", index=False)
    log.info("Exported product_loyalty.csv (top %s products)", len(product_loyalty))

    # 4) Order timing trends (Page 3 - Actionable Insights).
    order_trends = db.read_sql(
        """
        SELECT order_dow,
               order_hour_of_day,
               COUNT(*)                     AS orders,
               ROUND(AVG(order_value), 2)   AS avg_order_value
        FROM orders_clean
        GROUP BY order_dow, order_hour_of_day
        ORDER BY order_dow, order_hour_of_day
        """
    )
    order_trends.to_csv(out / "order_trends.csv", index=False)
    log.info("Exported order_trends.csv (%s rows)", len(order_trends))

    # 5) Department reorder opportunity = volume x propensity (Page 3).
    dept_opportunity = db.read_sql(
        """
        SELECT d.department,
               COUNT(*)                                 AS predicted_candidates,
               ROUND(AVG(rp.reorder_proba)::numeric, 4) AS avg_reorder_proba,
               SUM(rp.reordered_target)                 AS actual_reorders
        FROM reorder_predictions rp
        JOIN products p    ON p.product_id = rp.product_id
        JOIN departments d ON d.department_id = p.department_id
        GROUP BY d.department
        ORDER BY avg_reorder_proba DESC
        """
    )
    dept_opportunity.to_csv(out / "department_opportunity.csv", index=False)
    log.info("Exported department_opportunity.csv (%s departments)",
             len(dept_opportunity))

    log.info("All Tableau extracts written to %s", out)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    export()
