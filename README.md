# Cartographer — Instacart RFM Segmentation & Reorder Prediction

*Mapping customer loyalty and reorder behavior.*


An end-to-end retail analytics project: load Instacart-style transaction data
into **PostgreSQL**, clean it with **pandas / polars**, build an **RFM customer
segmentation**, train a **reorder-prediction model**, and ship a **three-page
dashboard** of actionable insights.

The repo runs out of the box on a **synthetic dataset** generated in the exact
[Instacart Market Basket Analysis](https://www.kaggle.com/c/instacart-market-basket-analysis)
CSV schema, so you can clone and run the whole pipeline with no Kaggle login.
Drop the real Kaggle CSVs into `data/raw/` and rerun to get real numbers — no
code changes required.

> **Why synthetic by default?** The real dataset is ~3 GB and behind a Kaggle
> login. To keep this repo `git clone && run`, `src/generate_sample_data.py`
> produces 5,000 customers / 1,000 products / ~60k orders in the **identical
> schema**, with a deliberately learnable reorder signal. Every result below is
> real output from that generated data. See *Using the real Kaggle data*.

---

## Results at a glance

*(synthetic sample — 5,000 customers, ~$3.66M modelled GMV)*

**RFM segmentation** sorts every customer into 10 canonical segments, each with
a recommended marketing action. Revenue concentrates in a few: Loyal Customers
(20.6% of GMV), At Risk (17.2%), and Potential Loyalists (14.8%) lead — so both
healthy *and* slipping segments carry the business.

**Reorder model** — predicts whether a customer will reorder a specific product
in their next order, at the `customer × product` grain over 14 engineered
features:

| Model | ROC-AUC | PR-AUC | F1\@0.5 |
|---|---|---|---|
| Logistic Regression (balanced) | 0.849 | 0.527 | 0.551 |
| **Gradient Boosting** (HistGBDT) | **0.862** | **0.560** | 0.407 |

Base reorder rate is 0.19, so PR-AUC of 0.56 is ~3× the no-skill baseline. Top
signals: how many times the user previously bought the item, the item's global
reorder rate, and how many orders since the user last bought it.

**Category loyalty** — produce (68.1%), dairy eggs (67.3%), and pets (66.6%)
have the highest reorder rates; produce, pets, and dairy eggs also top the
model's average reorder propensity, making them the prime nudge targets.

### Dashboard preview

Open [`dashboard/preview.html`](dashboard/preview.html) in any browser — it is
self-contained (no server, no dependencies) and renders the same three pages the
Tableau workbook specifies.

| Page 1 — Segments | Page 2 — Category loyalty | Page 3 — Reorder actions |
|---|---|---|
| ![Page 1](outputs/figures/dashboard_page1.png) | ![Page 2](outputs/figures/dashboard_page2.png) | ![Page 3](outputs/figures/dashboard_page3.png) |

---

## Architecture

```
 CSVs (data/raw/)          PostgreSQL                Python                 Outputs
 ────────────────   ──►   ─────────────    ──►   ──────────────    ──►   ──────────────
 orders, products,        raw tables             polars QC report        outputs/tableau/*.csv
 aisles, departments,     + views                pandas RFM scoring      outputs/figures/*.png
 order_products,          (load_to_postgres)     sklearn reorder model   data_quality_report.json
 product_prices*                                 SQL feature eng.        model_metrics.csv
                                                                         dashboard/preview.html
```

Stage-by-stage:

| Stage | Script | What it does |
|---|---|---|
| `generate` | `src/generate_sample_data.py` | Synthesize 7 CSVs in Instacart schema (skip if using real data) |
| `load` | `src/load_to_postgres.py` | Apply schema, bulk-`COPY` load, union prior+train, build views |
| `clean` | `src/clean_data.py` | polars data-quality report + materialize `orders_clean` |
| `rfm` | `src/rfm_segmentation.py` | R/F/M scores, quintile bands, 10-segment labels + actions |
| `model` | `src/reorder_model.py` | SQL feature engineering, train + evaluate reorder models |
| `export` | `src/export_for_tableau.py` | Aggregated CSV extracts for Tableau / the HTML preview |

Orchestrated by `run_pipeline.py`.

---

## Design decisions

A few honest notes about how this maps onto the real Instacart schema, which
ships **no prices and no calendar dates**:

- **Monetary (the "M" in RFM).** Instacart has no prices, so RFM's Monetary axis
  is undefined as-is. The repo adds a `product_prices` table with deterministic
  per-department price bands (an explicit, documented enrichment). Monetary =
  total modelled spend. With real prices, drop them into `product_prices` and
  the same code uses them; otherwise `_ensure_prices()` synthesizes the table so
  the pipeline still runs on raw Kaggle data.
- **Recency.** Instacart has no timestamps, only `days_since_prior_order`.
  Recency is defined as `days_since_prior_order` on the customer's most recent
  (`train`) order — lower = more recent = better. Frequency = total orders,
  Monetary = total modelled spend.
- **RFM scoring.** Quintile scores (1–5) via rank-based `qcut`; R is reversed so
  recent buyers score high. Segment labels follow the canonical R–F map
  (Champions, Loyal Customers, Potential Loyalists, New Customers, Promising,
  Need Attention, About to Sleep, At Risk, Can't Lose Them, Hibernating).
- **Reorder target.** Framed at the `(user, product)` grain: candidates are
  pairs the user bought in *prior* orders; the target is 1 if the product
  appears in the user's held-out *train* order. This mirrors the structure of
  the real Instacart competition.

---

## Quick start

### Prerequisites
- Python 3.11+ (required by the pinned pandas 3.x)
- PostgreSQL 14+ running locally

### 1. Install
```bash
git clone <your-repo-url> && cd cartographer
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure the database
Copy the example env file and adjust if your Postgres differs from the defaults:
```bash
cp .env.example .env
```
Defaults (overridable via env vars): host `localhost`, port `5432`, user
`analytics`, password `analytics`, database `instacart`. Create them once:
```bash
createuser analytics --pwprompt --superuser     # password: analytics
createdb instacart -O analytics
```

### 3. Run the whole pipeline
```bash
python run_pipeline.py
```
This generates the sample data, loads Postgres, cleans, segments, trains the
model, and writes all extracts and figures. Useful flags:
```bash
python run_pipeline.py --from rfm        # resume from a stage
python run_pipeline.py --only model      # run a single stage
python run_pipeline.py --no-generate     # skip synth data (use real CSVs)
```

### 4. View the results
- Dashboard: open `dashboard/preview.html`.
- Tableau build instructions: `dashboard/tableau_spec.md`.
- Figures: `outputs/figures/`. Extracts: `outputs/tableau/`.

---

## Using the real Kaggle data

1. Download the
   [Instacart Market Basket Analysis](https://www.kaggle.com/c/instacart-market-basket-analysis/data)
   CSVs (`orders.csv`, `products.csv`, `aisles.csv`, `departments.csv`,
   `order_products__prior.csv`, `order_products__train.csv`).
2. Drop them into `data/raw/`, replacing the generated files.
3. Run `python run_pipeline.py --no-generate`.

The loader synthesizes `product_prices` if you don't supply one, so Monetary
still works. Everything downstream — cleaning, RFM, model, extracts, dashboard —
runs unchanged. Expect the run to take longer and use more memory at full scale.

---

## Project layout

```
cartographer/
├── config.py                  # paths, DB config, sample/model params
├── run_pipeline.py            # orchestrator (stages: generate→load→clean→rfm→model→export)
├── requirements.txt
├── .env.example
├── sql/
│   ├── 01_schema.sql          # 6 tables mirroring Instacart + price enrichment + indexes
│   └── 02_analytics_views.sql # order value, customer orders, department loyalty views
├── src/
│   ├── db.py                  # cached SQLAlchemy engine + helpers
│   ├── generate_sample_data.py
│   ├── load_to_postgres.py
│   ├── clean_data.py          # polars data-quality checks
│   ├── rfm_segmentation.py
│   ├── reorder_model.py
│   └── export_for_tableau.py
├── dashboard/
│   ├── tableau_spec.md        # full 3-page Tableau workbook spec
│   ├── build_preview.py       # reproducible builder for the HTML preview
│   └── preview.html           # self-contained dashboard (generated)
├── data/raw/                  # CSVs (generated or real Kaggle data)
└── outputs/
    ├── tableau/*.csv          # aggregated extracts feeding the dashboard
    ├── figures/*.png          # model curves, RFM grids, dashboard renders
    ├── data_quality_report.json
    └── model_metrics.csv
```

---

## Tech stack

PostgreSQL · pandas · polars · SQLAlchemy · scikit-learn · matplotlib · Tableau
(spec + HTML preview).

## Notes & caveats

- All headline numbers come from the **synthetic** dataset and exist to
  demonstrate the pipeline; they are not real Instacart findings.
- The price table is a modelling convenience, clearly separated so it's obvious
  what's enrichment vs source data.
- Reproducible: fixed seeds (`seed=42`, `random_state=42`) throughout.
