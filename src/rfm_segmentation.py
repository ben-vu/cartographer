"""RFM (Recency, Frequency, Monetary) customer segmentation.

Definitions used here
---------------------
The public Instacart panel has no absolute calendar dates -- only
`days_since_prior_order`, the gap before each order. We therefore define:

* Recency  = days_since_prior_order recorded on the customer's most recent
             (eval_set='train') order, i.e. how long since they last shopped
             as of the snapshot. LOWER is better.
* Frequency = total number of orders the customer has placed. HIGHER is better.
* Monetary  = total spend across all the customer's orders, where each order's
             value comes from the synthetic price catalog. HIGHER is better.

Each dimension is scored into quintiles (1-5). The R and F scores are then
mapped to the widely-used 10-segment RFM matrix (Champions, Loyal, At Risk,
Hibernating, ...). Results are written to PostgreSQL (`rfm_segments`) and
exported for Tableau.
"""
from __future__ import annotations

import logging

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import config
from src import db

log = logging.getLogger(__name__)

# Canonical R-F segment map (keys are "<R><F>" with each score 1-5).
SEGMENT_MAP = {
    r"[1-2][1-2]": "Hibernating",
    r"[1-2][3-4]": "At Risk",
    r"[1-2]5": "Can't Lose Them",
    r"3[1-2]": "About to Sleep",
    r"33": "Need Attention",
    r"[3-4][4-5]": "Loyal Customers",
    r"41": "Promising",
    r"51": "New Customers",
    r"[4-5][2-3]": "Potential Loyalists",
    r"5[4-5]": "Champions",
}

# Suggested marketing action per segment (surfaced on the dashboard).
SEGMENT_ACTION = {
    "Champions": "Reward; early access, referrals, VIP perks.",
    "Loyal Customers": "Upsell higher-value items; ask for reviews.",
    "Potential Loyalists": "Membership/loyalty offers to deepen the habit.",
    "New Customers": "Onboarding support; build the second-order habit.",
    "Promising": "Targeted offers and brand awareness.",
    "Need Attention": "Limited-time offers on past favourites.",
    "About to Sleep": "Reactivate with relevant recommendations.",
    "At Risk": "Win-back campaign; personalised reorders.",
    "Can't Lose Them": "Aggressive win-back; they were valuable.",
    "Hibernating": "Low-cost reactivation; otherwise let lapse.",
}


def _build_rfm() -> pd.DataFrame:
    """Assemble the raw R, F, M values per customer from PostgreSQL."""
    # Frequency + Monetary from all orders; Recency from the latest order.
    fm = db.read_sql(
        """
        SELECT user_id,
               COUNT(*)                       AS frequency,
               ROUND(SUM(order_value), 2)     AS monetary,
               ROUND(AVG(order_value), 2)     AS avg_order_value,
               SUM(basket_size)               AS total_items
        FROM orders_clean
        GROUP BY user_id
        """
    )
    recency = db.read_sql(
        """
        SELECT user_id,
               days_since_prior_order AS recency
        FROM orders_clean
        WHERE eval_set = 'train'
        """
    )
    rfm = fm.merge(recency, on="user_id", how="left")
    # A handful of users may lack a train order; fall back to their max gap.
    rfm["recency"] = rfm["recency"].fillna(rfm["recency"].median())
    return rfm


def _score(rfm: pd.DataFrame) -> pd.DataFrame:
    """Add quintile scores R, F, M (1-5) and the segment label."""
    # Recency: lower days -> better -> score 5. Use rank to avoid duplicate-edge
    # errors from qcut on skewed integer distributions.
    rfm["R"] = pd.qcut(rfm["recency"].rank(method="first"),
                       config.RFM_BANDS, labels=[5, 4, 3, 2, 1]).astype(int)
    rfm["F"] = pd.qcut(rfm["frequency"].rank(method="first"),
                       config.RFM_BANDS, labels=[1, 2, 3, 4, 5]).astype(int)
    rfm["M"] = pd.qcut(rfm["monetary"].rank(method="first"),
                       config.RFM_BANDS, labels=[1, 2, 3, 4, 5]).astype(int)

    rfm["rfm_cell"] = rfm["R"].astype(str) + rfm["F"].astype(str)
    rfm["rfm_score"] = rfm[["R", "F", "M"]].sum(axis=1)
    rfm["segment"] = (
        rfm["rfm_cell"].replace(SEGMENT_MAP, regex=True)
    )
    rfm["action"] = rfm["segment"].map(SEGMENT_ACTION)
    return rfm


def _figures(rfm: pd.DataFrame) -> None:
    # Segment size + value.
    summary = (
        rfm.groupby("segment")
        .agg(customers=("user_id", "count"),
             total_monetary=("monetary", "sum"))
        .sort_values("customers", ascending=True)
    )
    fig, ax = plt.subplots(1, 2, figsize=(13, 6))
    summary["customers"].plot.barh(ax=ax[0], color="#3b7dd8")
    ax[0].set_title("Customers per RFM segment")
    ax[0].set_xlabel("customers")
    (summary["total_monetary"] / 1000).plot.barh(ax=ax[1], color="#2ca58d")
    ax[1].set_title("Total monetary value per segment ($000s)")
    ax[1].set_xlabel("revenue ($000s)")
    fig.tight_layout()
    fig.savefig(config.FIGURES / "rfm_segments.png", dpi=120)
    plt.close(fig)

    # R x F heatmap (customer counts).
    grid = rfm.pivot_table(index="R", columns="F", values="user_id",
                           aggfunc="count").reindex(index=[5, 4, 3, 2, 1])
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(grid, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(len(grid.columns)), grid.columns)
    ax.set_yticks(range(len(grid.index)), grid.index)
    ax.set_xlabel("Frequency score")
    ax.set_ylabel("Recency score")
    ax.set_title("RFM grid: customer counts")
    for i in range(grid.shape[0]):
        for j in range(grid.shape[1]):
            v = grid.iloc[i, j]
            if pd.notna(v):
                ax.text(j, i, int(v), ha="center", va="center", fontsize=9)
    fig.colorbar(im, ax=ax, label="customers")
    fig.tight_layout()
    fig.savefig(config.FIGURES / "rfm_grid.png", dpi=120)
    plt.close(fig)
    log.info("Saved figures -> %s", config.FIGURES)


def run() -> pd.DataFrame:
    rfm = _score(_build_rfm())

    db.write_df(
        rfm[["user_id", "recency", "frequency", "monetary", "avg_order_value",
             "total_items", "R", "F", "M", "rfm_score", "segment", "action"]],
        "rfm_segments",
    )
    out = config.TABLEAU / "rfm_segments.csv"
    rfm.to_csv(out, index=False)
    log.info("Exported %s", out)

    _figures(rfm)

    dist = (rfm["segment"].value_counts(normalize=True) * 100).round(1)
    log.info("Segment distribution (%%):\n%s", dist.to_string())
    return rfm


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()
