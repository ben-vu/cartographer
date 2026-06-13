"""Render a self-contained HTML preview of the 3-page dashboard from the
Tableau extracts. No external assets -> it opens offline and on GitHub Pages.

    python dashboard/build_preview.py

This mirrors what the Tableau workbook shows, so reviewers who don't have
Tableau can still see the insights. The real workbook spec lives in
dashboard/tableau_spec.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TAB = ROOT / "outputs" / "tableau"
OUT = ROOT / "dashboard" / "preview.html"


def _load() -> dict:
    seg = pd.read_csv(TAB / "segment_summary.csv")
    dept = pd.read_csv(TAB / "department_loyalty.csv")
    opp = pd.read_csv(TAB / "department_opportunity.csv")
    metrics = pd.read_csv(ROOT / "outputs" / "model_metrics.csv")
    prod = pd.read_csv(TAB / "product_loyalty.csv").head(8)

    total_customers = int(seg["customers"].sum())
    total_revenue = float(seg["total_monetary"].sum())
    gb = metrics.loc[metrics["model"] == "GradientBoosting"].iloc[0]

    # Order segments by a health ranking for the bar chart.
    health = ["Champions", "Loyal Customers", "Potential Loyalists",
              "New Customers", "Promising", "Need Attention", "About to Sleep",
              "At Risk", "Can't Lose Them", "Hibernating"]
    seg["order"] = seg["segment"].map({s: i for i, s in enumerate(health)})
    seg = seg.sort_values("order")

    return {
        "kpis": {
            "customers": total_customers,
            "revenue": round(total_revenue),
            "champions": int(seg.loc[seg.segment == "Champions", "customers"].iloc[0]),
            "at_risk": int(seg.loc[seg.segment.isin(
                ["At Risk", "Can't Lose Them"]), "customers"].sum()),
            "auc": float(gb["roc_auc"]),
            "pr_auc": float(gb["pr_auc"]),
        },
        "segments": seg[["segment", "customers", "total_monetary",
                         "pct_revenue", "avg_recency_days", "avg_frequency",
                         "avg_monetary", "recommended_action"]].to_dict("records"),
        "departments": dept.to_dict("records"),
        "opportunity": opp.to_dict("records"),
        "products": prod[["product_name", "department", "reorder_rate",
                          "times_purchased"]].to_dict("records"),
    }


# Segment -> health colour band.
SEG_COLOUR = {
    "Champions": "leaf", "Loyal Customers": "leaf", "Potential Loyalists": "leaf",
    "New Customers": "amber", "Promising": "amber", "Need Attention": "amber",
    "About to Sleep": "coral", "At Risk": "coral", "Can't Lose Them": "coral",
    "Hibernating": "ink",
}

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Instacart Customer Intelligence</title>
<style>
  :root {{
    --paper:#FBFAF6; --ink:#1C2321; --muted:#5E6B61; --line:#DDE3DA;
    --leaf:#2F7D4F; --leaf-deep:#1E5135; --amber:#E0922B; --coral:#CF5A38;
    --panel:#FFFFFF;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; background:var(--paper); color:var(--ink);
    font-family:ui-sans-serif,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased;
  }}
  .mono {{ font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
           font-variant-numeric:tabular-nums; }}
  header {{
    padding:26px clamp(18px,4vw,52px) 0; border-bottom:1px solid var(--line);
  }}
  .brand {{ display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; }}
  .brand h1 {{
    margin:0; font-size:clamp(22px,3.2vw,32px); font-weight:800;
    letter-spacing:-.02em;
  }}
  .brand .leaf {{ color:var(--leaf); }}
  .brand .meta {{ margin-left:auto; font-size:12px; color:var(--muted);
                  text-align:right; line-height:1.5; }}
  .sub {{ margin:6px 0 18px; color:var(--muted); font-size:14px; max-width:70ch; }}
  nav {{ display:flex; gap:2px; }}
  nav button {{
    appearance:none; border:1px solid var(--line); border-bottom:none;
    background:#F1F0EA; color:var(--muted); cursor:pointer;
    padding:11px 18px; font-size:13px; font-weight:650; letter-spacing:.01em;
    border-radius:9px 9px 0 0;
  }}
  nav button .n {{ font-family:ui-monospace,Menlo,monospace; color:var(--leaf);
                   margin-right:7px; }}
  nav button[aria-selected="true"] {{
    background:var(--panel); color:var(--ink); border-color:var(--line);
    box-shadow:0 -2px 0 var(--leaf) inset;
  }}
  main {{ padding:24px clamp(18px,4vw,52px) 60px; }}
  .page {{ display:none; }} .page.active {{ display:block; }}
  .grid {{ display:grid; gap:16px; }}
  .cols-3 {{ grid-template-columns:repeat(3,1fr); }}
  .cols-2 {{ grid-template-columns:1.3fr 1fr; }}
  @media (max-width:860px) {{ .cols-3,.cols-2 {{ grid-template-columns:1fr; }} }}
  .panel {{
    background:var(--panel); border:1px solid var(--line); border-radius:14px;
    padding:18px 20px;
  }}
  .panel h3 {{ margin:0 0 2px; font-size:15px; letter-spacing:-.01em; }}
  .panel .hint {{ margin:0 0 14px; color:var(--muted); font-size:12.5px; }}
  /* receipt-style KPI strip */
  .receipt {{
    background:var(--panel); border:1px solid var(--line); border-radius:14px;
    padding:0; overflow:hidden;
  }}
  .receipt .row {{
    display:flex; justify-content:space-between; align-items:baseline;
    padding:13px 20px; border-bottom:1px dashed var(--line);
  }}
  .receipt .row:last-child {{ border-bottom:none; }}
  .receipt .k {{ font-size:12.5px; color:var(--muted); text-transform:uppercase;
                 letter-spacing:.08em; }}
  .receipt .v {{ font-size:21px; font-weight:700; }}
  .receipt .v small {{ font-size:12px; color:var(--muted); font-weight:600; }}
  .bar-row {{ display:grid; grid-template-columns:148px 1fr 64px; align-items:center;
              gap:10px; margin:7px 0; font-size:13px; }}
  .bar-track {{ background:#EFEEE7; border-radius:6px; height:20px; position:relative;
                overflow:hidden; }}
  .bar-fill {{ display:block; height:100%; border-radius:6px; }}
  .lab {{ color:var(--ink); }}
  .val {{ text-align:right; color:var(--muted); }}
  .leaf-bg {{ background:var(--leaf); }} .amber-bg {{ background:var(--amber); }}
  .coral-bg {{ background:var(--coral); }} .ink-bg {{ background:#7C887E; }}
  .leaf-fg {{ color:var(--leaf); }} .coral-fg {{ color:var(--coral); }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th,td {{ text-align:left; padding:9px 8px; border-bottom:1px solid var(--line); }}
  th {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em;
        color:var(--muted); font-weight:650; }}
  td.num {{ text-align:right; font-family:ui-monospace,Menlo,monospace; }}
  .pill {{ display:inline-block; padding:2px 9px; border-radius:999px;
           font-size:11px; font-weight:700; }}
  .scorecard {{ display:flex; gap:26px; flex-wrap:wrap; align-items:center; }}
  .big {{ font-size:46px; font-weight:800; letter-spacing:-.03em; line-height:1; }}
  .footnote {{ color:var(--muted); font-size:12px; margin-top:26px;
               border-top:1px solid var(--line); padding-top:14px; }}
  .tag {{ font-family:ui-monospace,Menlo,monospace; font-size:11px;
          background:#EAF1EB; color:var(--leaf-deep); padding:3px 8px;
          border-radius:6px; border:1px solid #D3E3D6; }}
</style>
</head>
<body>
<header>
  <div class="brand">
    <h1>Instacart <span class="leaf">Customer Intelligence</span></h1>
    <div class="meta">
      <div class="mono">{customers:,} customers &middot; ${revenue:,} modelled GMV</div>
      <div>RFM segmentation &middot; reorder propensity model</div>
    </div>
  </div>
  <p class="sub">A growth analyst's cockpit: who the customers are, which
     categories earn their loyalty, and which reorders to nudge next.</p>
  <nav id="tabs">
    <button data-p="0" aria-selected="true"><span class="n">01</span>Customer segments</button>
    <button data-p="1"><span class="n">02</span>Category loyalty</button>
    <button data-p="2"><span class="n">03</span>Reorder actions</button>
  </nav>
</header>
<main>
  <!-- PAGE 1 -->
  <section class="page active" id="p0">
    <div class="grid cols-3" style="margin-bottom:16px">
      <div class="receipt">
        <div class="row"><span class="k">Active customers</span><span class="v mono">{customers:,}</span></div>
        <div class="row"><span class="k">Champions</span><span class="v mono leaf-fg">{champions:,} <small>most valuable</small></span></div>
        <div class="row"><span class="k">At-risk / can't-lose</span><span class="v mono coral-fg">{at_risk:,} <small>win-back now</small></span></div>
      </div>
      <div class="panel" style="grid-column:span 2">
        <h3>Customers by RFM segment</h3>
        <p class="hint">Bar length = customers. Colour = segment health
           (green grow &middot; amber nurture &middot; coral rescue).</p>
        <div id="segBars"></div>
      </div>
    </div>
    <div class="panel">
      <h3>Where the revenue concentrates</h3>
      <p class="hint">Share of modelled GMV by segment &mdash; the top three
         healthy segments and the "Can't Lose Them" group carry the business.</p>
      <div id="revBars"></div>
    </div>
  </section>

  <!-- PAGE 2 -->
  <section class="page" id="p1">
    <div class="grid cols-2">
      <div class="panel">
        <h3>Which categories drive loyalty</h3>
        <p class="hint">Reorder rate = share of category line-items that were a
           repeat purchase. Higher = stickier category.</p>
        <div id="deptBars"></div>
      </div>
      <div class="panel">
        <h3>Loyalty vs reach</h3>
        <p class="hint">Each bubble is a department. X = reorder rate,
           Y = customers reached, size = volume. Top-right = strategic.</p>
        <svg id="bubble" viewBox="0 0 420 320" width="100%" role="img"></svg>
      </div>
    </div>
    <div class="panel" style="margin-top:16px">
      <h3>Stickiest individual products</h3>
      <p class="hint">Highest reorder rates among products with meaningful volume.</p>
      <table id="prodTable"></table>
    </div>
  </section>

  <!-- PAGE 3 -->
  <section class="page" id="p2">
    <div class="grid cols-2">
      <div class="panel">
        <h3>Reorder model scorecard</h3>
        <p class="hint">Gradient-boosting classifier predicting next-order
           reorders at the customer&times;product grain.</p>
        <div class="scorecard">
          <div><div class="big leaf-fg mono">{auc:.2f}</div><div class="hint">ROC-AUC</div></div>
          <div><div class="big mono">{pr_auc:.2f}</div><div class="hint">PR-AUC (base {base:.2f})</div></div>
          <div style="max-width:30ch"><span class="tag">14 features</span>
            <p class="hint" style="margin-top:8px">Top signals: how often the
            user bought the item, the item's global reorder rate, and orders
            since last purchase.</p></div>
        </div>
      </div>
      <div class="panel">
        <h3>Highest-propensity categories to nudge</h3>
        <p class="hint">Average predicted reorder probability across each
           department's candidate pairs.</p>
        <div id="oppBars"></div>
      </div>
    </div>
    <div class="panel" style="margin-top:16px">
      <h3>Next best action by segment</h3>
      <p class="hint">Pair the propensity model with the segment playbook:
         target high-probability reorders inside each segment's strategy.</p>
      <table id="actionTable"></table>
    </div>
  </section>

  <p class="footnote">Static preview generated from <span class="mono">outputs/tableau/*.csv</span>
     by <span class="mono">dashboard/build_preview.py</span>. The production
     three-page workbook is specified in <span class="mono">dashboard/tableau_spec.md</span>.
     Figures come from the synthetic sample dataset; swap in the real Kaggle CSVs to refresh.</p>
</main>
<script>
const DATA = {data_json};
const COL = {{leaf:'leaf',amber:'amber',coral:'coral',ink:'ink'}};
const SEGCOL = {seg_colour_json};
const fmt = n => n.toLocaleString();

function barChart(el, rows, {{label, value, max, colour, suffix='', fmtv}}) {{
  const m = max || Math.max(...rows.map(value));
  el.innerHTML = rows.map(r => {{
    const v = value(r), w = Math.max(2, 100*v/m);
    const c = (colour ? colour(r) : 'leaf') + '-bg';
    const shown = fmtv ? fmtv(v) : v;
    return `<div class="bar-row"><span class="lab">${{label(r)}}</span>
      <span class="bar-track"><span class="bar-fill ${{c}}" style="width:${{w}}%"></span></span>
      <span class="val mono">${{shown}}${{suffix}}</span></div>`;
  }}).join('');
}}

// Page 1
barChart(document.getElementById('segBars'), DATA.segments, {{
  label:r=>r.segment, value:r=>r.customers,
  colour:r=>SEGCOL[r.segment], fmtv:v=>fmt(v)
}});
barChart(document.getElementById('revBars'),
  [...DATA.segments].sort((a,b)=>b.total_monetary-a.total_monetary), {{
  label:r=>r.segment, value:r=>r.pct_revenue,
  colour:r=>SEGCOL[r.segment], suffix:'%'
}});

// Page 2
barChart(document.getElementById('deptBars'), DATA.departments, {{
  label:r=>r.department, value:r=>r.reorder_rate, max:0.75,
  colour:r=> r.reorder_rate>=0.62?'leaf':(r.reorder_rate>=0.56?'amber':'coral'),
  fmtv:v=>(100*v).toFixed(1), suffix:'%'
}});
// bubble
(function(){{
  const svg=document.getElementById('bubble'); const W=420,H=320,pad=46;
  const ds=DATA.departments;
  const xs=ds.map(d=>d.reorder_rate), ys=ds.map(d=>d.unique_customers), vs=ds.map(d=>d.line_items);
  const xmin=Math.min(...xs)-0.01, xmax=Math.max(...xs)+0.01;
  const ymin=Math.min(...ys)*0.95, ymax=Math.max(...ys)*1.03, vmax=Math.max(...vs);
  const X=v=>pad+(W-pad-14)*(v-xmin)/(xmax-xmin);
  const Y=v=>H-pad-(H-pad-14)*(v-ymin)/(ymax-ymin);
  let s=`<line x1="${{pad}}" y1="${{H-pad}}" x2="${{W-8}}" y2="${{H-pad}}" stroke="#DDE3DA"/>
         <line x1="${{pad}}" y1="14" x2="${{pad}}" y2="${{H-pad}}" stroke="#DDE3DA"/>
         <text x="${{(W)/2}}" y="${{H-12}}" fill="#5E6B61" font-size="11" text-anchor="middle">reorder rate &rarr;</text>
         <text x="14" y="${{H/2}}" fill="#5E6B61" font-size="11" text-anchor="middle" transform="rotate(-90,14,${{H/2}})">customers reached &rarr;</text>`;
  ds.forEach(d=>{{
    const r=6+18*Math.sqrt(d.line_items/vmax);
    const c=d.reorder_rate>=0.62?'#2F7D4F':(d.reorder_rate>=0.56?'#E0922B':'#CF5A38');
    s+=`<circle cx="${{X(d.reorder_rate)}}" cy="${{Y(d.unique_customers)}}" r="${{r}}"
         fill="${{c}}" fill-opacity="0.22" stroke="${{c}}" stroke-width="1.4"/>`;
  }});
  ds.filter(d=>d.reorder_rate>=0.60||d.line_items>40000).forEach(d=>{{
    s+=`<text x="${{X(d.reorder_rate)+2}}" y="${{Y(d.unique_customers)-10}}" font-size="10"
         fill="#1C2321" text-anchor="middle">${{d.department}}</text>`;
  }});
  svg.innerHTML=s;
}})();
document.getElementById('prodTable').innerHTML =
  `<tr><th>Product</th><th>Department</th><th style="text-align:right">Reorder rate</th><th style="text-align:right">Purchases</th></tr>`+
  DATA.products.map(p=>`<tr><td>${{p.product_name}}</td><td>${{p.department}}</td>
    <td class="num">${{(100*p.reorder_rate).toFixed(1)}}%</td>
    <td class="num">${{fmt(p.times_purchased)}}</td></tr>`).join('');

// Page 3
barChart(document.getElementById('oppBars'),
  DATA.opportunity.slice(0,10), {{
  label:r=>r.department, value:r=>r.avg_reorder_proba, max:0.26,
  colour:r=>'leaf', fmtv:v=>(100*v).toFixed(1), suffix:'%'
}});
const SEGCOLOR_PILL={{leaf:'#EAF1EB',amber:'#FBF0DD',coral:'#FAE5DD',ink:'#ECEEEB'}};
const SEGTXT={{leaf:'#1E5135',amber:'#8A5A12',coral:'#8F3318',ink:'#3B433D'}};
document.getElementById('actionTable').innerHTML =
  `<tr><th>Segment</th><th style="text-align:right">Customers</th><th style="text-align:right">Avg spend</th><th>Recommended action</th></tr>`+
  DATA.segments.map(s=>{{const c=SEGCOL[s.segment];
   return `<tr><td><span class="pill" style="background:${{SEGCOLOR_PILL[c]}};color:${{SEGTXT[c]}}">${{s.segment}}</span></td>
    <td class="num">${{fmt(s.customers)}}</td>
    <td class="num">$${{s.avg_monetary.toFixed(0)}}</td>
    <td>${{s.recommended_action}}</td></tr>`;}}).join('');

// tabs
const tabs=document.getElementById('tabs');
tabs.addEventListener('click',e=>{{
  const b=e.target.closest('button'); if(!b)return;
  [...tabs.children].forEach(x=>x.setAttribute('aria-selected', x===b));
  document.querySelectorAll('.page').forEach((p,i)=>
    p.classList.toggle('active', i===+b.dataset.p));
}});
</script>
</body>
</html>
"""


def build() -> None:
    d = _load()
    html = TEMPLATE.format(
        customers=d["kpis"]["customers"],
        revenue=d["kpis"]["revenue"],
        champions=d["kpis"]["champions"],
        at_risk=d["kpis"]["at_risk"],
        auc=d["kpis"]["auc"],
        pr_auc=d["kpis"]["pr_auc"],
        base=0.186,
        data_json=json.dumps(d),
        seg_colour_json=json.dumps(SEG_COLOUR),
    )
    OUT.write_text(html)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
