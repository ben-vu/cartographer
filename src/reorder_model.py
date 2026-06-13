"""Predict whether a customer will reorder a specific product in their next order.

This is the classic Instacart problem framed at the (user, product) grain:

    candidates : every (user, product) pair the user bought in PRIOR orders
    target     : 1 if that product appears in the user's next (train) order

Features are engineered in PostgreSQL (cheap, and scales to the full dataset)
across three grains -- user, product, and user x product -- then a baseline
Logistic Regression and a Gradient Boosting model are trained and compared.
Metrics, plots, and a scored output for Tableau are written to outputs/.
"""
from __future__ import annotations

import logging

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import config
from src import db

log = logging.getLogger(__name__)

FEATURE_SQL = """
DROP TABLE IF EXISTS reorder_features;
CREATE TABLE reorder_features AS
WITH prior AS (
    SELECT op.order_id, op.product_id, op.add_to_cart_order, op.reordered,
           o.user_id, o.order_number
    FROM order_products op
    JOIN orders o ON o.order_id = op.order_id
    WHERE op.eval_set = 'prior'
),
train_users AS (
    SELECT DISTINCT user_id FROM orders WHERE eval_set = 'train'
),
u_orders AS (
    SELECT user_id,
           MAX(order_number)            AS u_total_orders,
           AVG(basket_size)             AS u_avg_basket,
           AVG(days_since_prior_order)  AS u_avg_dspo
    FROM orders_clean
    WHERE eval_set = 'prior'
    GROUP BY user_id
),
u_reorder AS (
    SELECT user_id, AVG(reordered::float) AS u_reorder_rate
    FROM prior GROUP BY user_id
),
p_stats AS (
    SELECT product_id,
           COUNT(*)                      AS p_total_purchases,
           AVG(reordered::float)         AS p_reorder_rate,
           COUNT(DISTINCT user_id)       AS p_unique_users,
           AVG(add_to_cart_order::float) AS p_avg_cart_pos
    FROM prior GROUP BY product_id
),
up AS (
    SELECT user_id, product_id,
           COUNT(*)                      AS up_orders,
           AVG(add_to_cart_order::float) AS up_avg_cart_pos,
           MAX(order_number)             AS up_last_order_number,
           MIN(order_number)             AS up_first_order_number
    FROM prior GROUP BY user_id, product_id
),
train_set AS (
    SELECT o.user_id, op.product_id
    FROM order_products op
    JOIN orders o ON o.order_id = op.order_id
    WHERE op.eval_set = 'train'
)
SELECT
    up.user_id, up.product_id,
    uo.u_total_orders, uo.u_avg_basket, uo.u_avg_dspo, ur.u_reorder_rate,
    ps.p_total_purchases, ps.p_reorder_rate, ps.p_unique_users, ps.p_avg_cart_pos,
    up.up_orders, up.up_avg_cart_pos,
    (up.up_orders::float / uo.u_total_orders)                  AS up_order_rate,
    (uo.u_total_orders - up.up_last_order_number)              AS up_orders_since_last,
    (uo.u_total_orders - up.up_first_order_number + 1)         AS up_tenure_orders,
    (up.up_orders::float
        / NULLIF(uo.u_total_orders - up.up_first_order_number + 1, 0))
                                                               AS up_purchase_rate,
    CASE WHEN ts.product_id IS NOT NULL THEN 1 ELSE 0 END      AS reordered_target
FROM up
JOIN train_users tu ON tu.user_id = up.user_id
JOIN u_orders   uo ON uo.user_id = up.user_id
JOIN u_reorder  ur ON ur.user_id = up.user_id
JOIN p_stats    ps ON ps.product_id = up.product_id
LEFT JOIN train_set ts
       ON ts.user_id = up.user_id AND ts.product_id = up.product_id;
"""

FEATURES = [
    "u_total_orders", "u_avg_basket", "u_avg_dspo", "u_reorder_rate",
    "p_total_purchases", "p_reorder_rate", "p_unique_users", "p_avg_cart_pos",
    "up_orders", "up_avg_cart_pos", "up_order_rate", "up_orders_since_last",
    "up_tenure_orders", "up_purchase_rate",
]


def _build_features() -> pd.DataFrame:
    log.info("Engineering (user, product) features in PostgreSQL...")
    db.run_sql_file_text(FEATURE_SQL)
    df = db.read_sql("SELECT * FROM reorder_features")
    df[FEATURES] = df[FEATURES].fillna(0)
    log.info("Feature matrix: %s rows | positive rate %.3f",
             f"{len(df):,}", df["reordered_target"].mean())
    return df


def _evaluate(name, y_true, proba, thr=0.5) -> dict:
    pred = (proba >= thr).astype(int)
    metrics = {
        "model": name,
        "roc_auc": round(roc_auc_score(y_true, proba), 4),
        "pr_auc": round(average_precision_score(y_true, proba), 4),
        "f1@0.5": round(f1_score(y_true, pred), 4),
    }
    return metrics


def _plots(y_true, proba_lr, proba_gb, gb_model, X_test, y_test) -> None:
    # ROC + PR curves comparing both models.
    fig, ax = plt.subplots(1, 2, figsize=(13, 5.5))
    for name, proba, color in [("Logistic Reg.", proba_lr, "#3b7dd8"),
                               ("Grad. Boosting", proba_gb, "#2ca58d")]:
        fpr, tpr, _ = roc_curve(y_true, proba)
        ax[0].plot(fpr, tpr, color=color,
                   label=f"{name} (AUC={roc_auc_score(y_true, proba):.3f})")
        prec, rec, _ = precision_recall_curve(y_true, proba)
        ax[1].plot(rec, prec, color=color,
                   label=f"{name} (AP={average_precision_score(y_true, proba):.3f})")
    ax[0].plot([0, 1], [0, 1], "k--", alpha=0.4)
    ax[0].set(xlabel="False positive rate", ylabel="True positive rate",
              title="ROC curve")
    ax[0].legend()
    ax[1].axhline(y_true.mean(), ls="--", color="grey", alpha=0.6,
                  label=f"baseline ({y_true.mean():.2f})")
    ax[1].set(xlabel="Recall", ylabel="Precision", title="Precision-Recall curve")
    ax[1].legend()
    fig.tight_layout()
    fig.savefig(config.FIGURES / "reorder_model_curves.png", dpi=120)
    plt.close(fig)

    # Permutation importance for the gradient boosting model.
    log.info("Computing permutation importance...")
    imp = permutation_importance(gb_model, X_test, y_test, n_repeats=5,
                                 random_state=config.MODEL["random_state"],
                                 scoring="roc_auc", n_jobs=1)
    order = np.argsort(imp.importances_mean)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh(np.array(FEATURES)[order], imp.importances_mean[order],
            xerr=imp.importances_std[order], color="#2ca58d")
    ax.set_title("Permutation importance (drop in ROC-AUC) - Gradient Boosting")
    ax.set_xlabel("importance")
    fig.tight_layout()
    fig.savefig(config.FIGURES / "reorder_feature_importance.png", dpi=120)
    plt.close(fig)
    return imp


def run() -> pd.DataFrame:
    df = _build_features()
    X = df[FEATURES]
    y = df["reordered_target"]

    X_train, X_test, y_train, y_test, idx_train, idx_test = train_test_split(
        X, y, df.index,
        test_size=config.MODEL["test_size"],
        random_state=config.MODEL["random_state"],
        stratify=y,
    )

    # Baseline: logistic regression (scaled).
    lr = Pipeline([
        ("scale", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
    ])
    lr.fit(X_train, y_train)
    proba_lr = lr.predict_proba(X_test)[:, 1]

    # Gradient boosting.
    gb = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.08, max_depth=6,
        l2_regularization=1.0, random_state=config.MODEL["random_state"],
    )
    gb.fit(X_train, y_train)
    proba_gb = gb.predict_proba(X_test)[:, 1]

    results = pd.DataFrame([
        _evaluate("LogisticRegression", y_test, proba_lr),
        _evaluate("GradientBoosting", y_test, proba_gb),
    ])
    log.info("Model comparison:\n%s", results.to_string(index=False))
    log.info("Gradient Boosting classification report @0.5:\n%s",
             classification_report(y_test, (proba_gb >= 0.5).astype(int),
                                    digits=3))
    log.info("Confusion matrix (GB @0.5):\n%s",
             confusion_matrix(y_test, (proba_gb >= 0.5).astype(int)))

    _plots(y_test, proba_lr, proba_gb, gb, X_test, y_test)
    results.to_csv(config.OUTPUTS / "model_metrics.csv", index=False)

    # Score the full candidate set with the better model and export for Tableau.
    df["reorder_proba"] = gb.predict_proba(X)[:, 1]
    scored = df[["user_id", "product_id", "up_orders", "up_orders_since_last",
                 "p_reorder_rate", "reorder_proba", "reordered_target"]]
    scored.to_csv(config.TABLEAU / "reorder_predictions.csv", index=False)
    db.write_df(scored, "reorder_predictions")  # for downstream SQL joins
    log.info("Exported scored predictions -> %s",
             config.TABLEAU / "reorder_predictions.csv")
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()
