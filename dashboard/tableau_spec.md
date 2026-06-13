# Tableau Workbook Specification — *Instacart Customer Intelligence*

This document specifies the production three-page Tableau workbook. The sandbox
cannot emit a binary `.twbx`, so this spec is the source of truth: it names every
data source, sheet, calculated field, and layout choice needed to rebuild the
workbook exactly. The self-contained `dashboard/preview.html` renders the same
three pages from the same extracts so reviewers can see the intended result
without opening Tableau.

All figures below come from the synthetic sample dataset (5,000 customers,
~$3.66M modelled GMV). Swapping in the real Kaggle CSVs and re-running the
pipeline regenerates every extract; the workbook refreshes unchanged.

---

## Data sources (extracts)

Each page is fed by a small, pre-aggregated CSV written to
`outputs/tableau/` by `src/export_for_tableau.py`. Keeping aggregation in
SQL/Python (not in Tableau) means the workbook stays fast and the logic stays
version-controlled and testable.

| Extract | Grain | Rows | Feeds |
|---|---|---|---|
| `segment_summary.csv` | one row per RFM segment | 10 | Page 1 |
| `rfm_segments.csv` | one row per customer | 5,000 | Page 1 (detail) |
| `department_loyalty.csv` | one row per department | 17 | Page 2 |
| `product_loyalty.csv` | top 200 products by volume | 200 | Page 2 |
| `department_opportunity.csv` | one row per department | 17 | Page 3 |
| `segment_summary.csv` | (reused) | 10 | Page 3 action table |
| `order_trends.csv` | day-of-week × hour | 168 | optional heatmap |

Connect each CSV as a **text file** data source. No joins are required for the
core sheets; Page 2's bubble chart and Page 3's department view each read a
single extract. If you prefer a single data source, `rfm_segments.csv` and
`reorder_predictions.csv` can be related on `user_id` / `product_id`, but the
pre-aggregated extracts above are the recommended, performant path.

---

## Global styling

- **Palette.** Leaf green `#2F7D4F` (healthy / grow), amber `#E0922B`
  (nurture), coral `#CF5A38` (rescue), slate `#7C887E` (dormant), ink
  `#1C2321` text on paper `#FBFAF6`.
- **Segment colour rule** (reused on every page) — a single calculated field
  so colour is consistent workbook-wide:

  ```
  // [Segment Health]
  CASE [segment]
    WHEN "Champions" THEN "Grow"   WHEN "Loyal Customers" THEN "Grow"
    WHEN "Potential Loyalists" THEN "Grow"
    WHEN "New Customers" THEN "Nurture" WHEN "Promising" THEN "Nurture"
    WHEN "Need Attention" THEN "Nurture"
    WHEN "About to Sleep" THEN "Rescue" WHEN "At Risk" THEN "Rescue"
    WHEN "Can't Lose Them" THEN "Rescue"
    WHEN "Hibernating" THEN "Dormant"
  END
  ```
  Map the four health values to the four palette colours above.
- **Fonts.** Tableau Bold for titles; tabular/monospace for KPI figures so
  digits align.
- **Number formats.** GMV as `$#,##0`; rates and shares as `0.0%`; counts as
  `#,##0`.
- Hide field labels for rows/columns on bar sheets; lead with a one-line
  subtitle stating how to read the view.

---

## Page 1 — Customer Segmentation

**Goal.** Answer "who are our customers, and where does the money sit?" in five
seconds.

**Source:** `segment_summary.csv` (KPIs + both bar charts); `rfm_segments.csv`
(optional scatter / drill detail).

### Sheets

1. **KPI — Active customers.** `SUM([customers])` → `5,000`. BAN (big-ass
   number) text sheet.
2. **KPI — Champions.** Filter `[segment] = "Champions"`, show
   `SUM([customers])` → `404`, caption "most valuable".
3. **KPI — At-risk / Can't-lose.** Filter segment to `At Risk` + `Can't Lose
   Them`, `SUM([customers])` → `1,209`, caption "win-back now".
4. **Customers by RFM segment** (horizontal bar).
   - Rows: `[segment]` sorted by `[customers]` descending.
   - Columns: `SUM([customers])`.
   - Colour: `[Segment Health]`.
   - Label: `SUM([customers])` at end of bar.
5. **Where revenue concentrates** (horizontal bar).
   - Rows: `[segment]` sorted by `[pct_revenue]` descending.
   - Columns: `SUM([pct_revenue])` (already a share; format `0.0%`).
   - Colour: `[Segment Health]`.
   - Reference: in the sample, Loyal Customers 20.6%, At Risk 17.2%,
     Potential Loyalists 14.8% lead — i.e. healthy segments **and** a large
     at-risk base both carry revenue, which motivates Page 3.

### Layout
Top KPI strip (3 BANs) → left: segment-count bar; right: revenue-share bar.
Title: **"Customer Segmentation — RFM."** Subtitle: "Bar length = customers;
colour = segment health (grow · nurture · rescue · dormant)."

### Interactivity
Use **[segment]** as a dashboard filter action so clicking a bar filters the
revenue chart and (if added) the customer scatter. Add a tooltip showing
`avg_recency_days`, `avg_frequency`, `avg_monetary`, `avg_rfm_score`.

---

## Page 2 — Category Loyalty

**Goal.** Identify which product categories earn repeat purchases (stickiness)
and which combine stickiness with reach.

**Source:** `department_loyalty.csv` (bars + bubble); `product_loyalty.csv`
(table).

### Calculated field
```
// [Loyalty Band]  — colours the loyalty bars
IF [reorder_rate] >= 0.62 THEN "High"
ELSEIF [reorder_rate] >= 0.56 THEN "Medium"
ELSE "Low" END
```
Map High→leaf, Medium→amber, Low→coral.

### Sheets

1. **Categories by loyalty** (horizontal bar).
   - Rows: `[department]` sorted by `[reorder_rate]` desc.
   - Columns: `AVG([reorder_rate])` (format `0.0%`).
   - Colour: `[Loyalty Band]`.
   - Sample leaders: produce 68.1%, dairy eggs 67.3%, pets 66.6%, dry goods
     pasta 62.5%, pantry 61.9%.
2. **Loyalty vs reach** (scatter / bubble).
   - Columns: `AVG([reorder_rate])` (X = stickiness).
   - Rows: `SUM([unique_customers])` (Y = reach).
   - Size: `SUM([line_items])` (volume).
   - Colour: `[Loyalty Band]`; Label: `[department]`.
   - Read: **top-right = strategic** (sticky *and* broad — produce, dairy
     eggs). Bottom-left = neither; candidates to de-prioritise or fix.
3. **Stickiest individual products** (text table).
   - From `product_loyalty.csv`, sort by `[reorder_rate]` desc, filter
     `[times_purchased] >= 100` so the rate is meaningful.
   - Columns: product name, department, `reorder_rate` (`0.0%`),
     `times_purchased`.

### Layout
Left: loyalty bar (full height). Right-top: bubble scatter. Bottom: product
table spanning width. Title: **"Category Loyalty."** Subtitle: "Reorder rate =
share of a category's line-items that were repeat purchases. Higher = stickier."

### Interactivity
Hover bubble → tooltip with department, reorder rate, customers reached, line
items. Clicking a department bar filters the product table to that department.

---

## Page 3 — Reorder Actions

**Goal.** Turn the propensity model into "what to do next, for whom."

**Source:** `model_metrics.csv` (scorecard), `department_opportunity.csv`
(propensity bars), `segment_summary.csv` (action table).

### Sheets

1. **Model scorecard** (BANs + text).
   - `ROC-AUC = 0.86`, `PR-AUC = 0.56` (base rate 0.19), with a caption
     naming top signals: how often the user bought the item, the item's global
     reorder rate, and orders since the user last bought it.
   - These come from `model_metrics.csv` (GradientBoosting row). Hard-code as a
     caption or load the CSV as a tiny data source.
2. **Highest-propensity categories to nudge** (horizontal bar).
   - Rows: `[department]` sorted by `[avg_reorder_proba]` desc.
   - Columns: `AVG([avg_reorder_proba])` (format `0.0%`).
   - Colour: leaf (single hue — this is an opportunity ranking, not health).
   - Sample leaders: produce 24.6%, pets 23.6%, dairy eggs 23.3%.
3. **Next best action by segment** (text table — the centrepiece).
   - Rows: `[segment]` (sorted by `[avg_rfm_score]` desc so Champions on top).
   - Columns: `customers`, `avg_monetary` ($), `recommended_action`.
   - Colour the segment label with `[Segment Health]` (pill effect).
   - The `recommended_action` text ships in `segment_summary.csv`, so the
     playbook is data-driven, not hand-typed in Tableau.

### The combined narrative (write this as the dashboard caption)
> The model scores every customer×product pair for reorder probability. Page 1
> says *who* each customer is; this page says *what to send them*. Pair the two:
> e.g. for **At Risk** customers (813 people, $776 avg spend) push a win-back
> with their **high-propensity produce/dairy** items — the categories the model
> says they're most likely to repurchase.

### Layout
Top: scorecard (left) + propensity bars (right). Bottom: action table full
width. Title: **"Reorder Actions."** Subtitle: "Predicted next-order reorders
× segment playbook = targeted campaigns."

### Interactivity
A dashboard parameter / filter on `[Segment Health]` lets a marketer isolate
Grow vs Rescue audiences across all three sheets.

---

## Rebuild checklist

1. Run the pipeline (`python run_pipeline.py`) to (re)generate
   `outputs/tableau/*.csv`.
2. In Tableau, connect each extract as a text file data source.
3. Create the three shared calculated fields (`[Segment Health]`,
   `[Loyalty Band]`) once and reuse.
4. Build the sheets per page above; assemble three dashboards.
5. Add the two filter actions (segment on Page 1, department on Page 2) and the
   health filter on Page 3.
6. Set dashboard size to 1280×900 (matches the HTML preview) or "Automatic".
7. Save as `Instacart_Customer_Intelligence.twbx` (packaged, so the extracts
   travel with it).
