#!/usr/bin/env python3
"""Emit HTML for pages 1-FR and 2-FR of the infographic from france_full_results.json.

Writes fr_pages_fragment.html, ready to be inserted into infographic_dayahead.html
between the existing page 2 and page 3.
"""
import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import json
import os

DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(DIR, "france_full_results.json")
OUT = os.path.join(DIR, "fr_pages_fragment.html")
YEARS = ["2021", "2022", "2023", "2024", "2025"]


def fmt_int(v):
    if v is None:
        return "—"
    return f"{int(round(v)):,}"


def fmt_num(v, decimals=2):
    if v is None:
        return "—"
    return f"{v:,.{decimals}f}"


def fmt_pct(v, decimals=1):
    if v is None:
        return "—"
    return f"{v:.{decimals}f}%"


def fmt_signed(v, decimals=2):
    if v is None:
        return "—"
    return f"{v:+,.{decimals}f}"


def render_period_row(year, period, fields, diff_cls="val-diff-neg"):
    """One row for a period-based table (longest neg, max loss, worst 24h, etc.).

    fields = list of dicts describing each cell to render. But here we go direct.
    """
    if period is None:
        return (f'<tr><td>{year}</td><td colspan="5" style="color:#9ca3af">no data</td></tr>')
    # Compact period label
    start = period["start"]
    end = period["end"]
    hrs = period["hours"]
    days = period["days"]
    if days >= 1:
        dur = f"{days:.1f}d / {hrs:.0f}h"
    else:
        dur = f"{hrs:.0f}h"
    # Trim year from display
    s_disp = start[5:] if start.startswith(year) else start
    e_disp = end[5:] if end.startswith(year) else end
    period_disp = f"{s_disp} → {e_disp}"
    return f"""<tr>
  <td>{year}</td>
  <td style="font-size:11px">{period_disp}</td>
  <td>{dur}</td>
  <td class="val-imb">{fmt_num(period['imb_avg'])}<br><span style="font-size:11px;font-weight:400">({fmt_int(period['imb_total'])})</span></td>
  <td class="val-da">{fmt_signed(period['da_avg'])}<br><span style="font-size:11px;font-weight:400">({fmt_int(period['da_total']) if period['da_total'] and period['da_total'] >= 0 else ('(' + fmt_int(period['da_total']) + ')')})</span></td>
  <td class="{diff_cls}">{fmt_signed(period['diff_avg'])}<br><span style="font-size:11px;font-weight:400">({fmt_int(period['diff_total'])})</span></td>
</tr>"""


def render_worst_cost_row(year, period):
    if period is None:
        return f'<tr><td>{year}</td><td colspan="6" style="color:#9ca3af">no data</td></tr>'
    s_disp = period["start"][5:]
    e_disp = period["end"][5:]
    return f"""<tr>
  <td>{year}</td>
  <td style="font-size:10px">{s_disp} → {e_disp}</td>
  <td class="val-imb">{fmt_signed(period['imb_avg'])}<br><span style="font-size:11px;font-weight:400">({fmt_int(period['imb_total'])})</span></td>
  <td class="val-da">{fmt_signed(period['da_avg'])}<br><span style="font-size:11px;font-weight:400">({fmt_int(period['da_total'])})</span></td>
  <td class="val-diff-neg">{fmt_signed(period['diff_avg'])}<br><span style="font-size:11px;font-weight:400">({fmt_int(period['diff_total'])})</span></td>
  <td class="val-diff-neg">{'+' if period.get('premium_pct', 0) >= 0 else ''}{int(round(period.get('premium_pct', 0)))}%</td>
</tr>"""


def render_worst_24h_row(year, period):
    if period is None:
        return f'<tr><td>{year}</td><td colspan="5" style="color:#9ca3af">no data</td></tr>'
    return f"""<tr>
  <td>{year}</td>
  <td style="font-size:11px">{period['start'][5:10]}</td>
  <td class="val-imb">{fmt_signed(period['imb_avg'])}<br><span style="font-size:11px;font-weight:400">({fmt_int(period['imb_total'])})</span></td>
  <td class="val-da">{fmt_signed(period['da_avg'])}<br><span style="font-size:11px;font-weight:400">({fmt_int(period['da_total'])})</span></td>
  <td class="val-diff-neg">{fmt_signed(period['diff_avg'])}<br><span style="font-size:11px;font-weight:400">({fmt_int(period['diff_total'])})</span></td>
  <td class="val-diff-neg">+{int(round(period.get('premium_pct', 0)))}%</td>
</tr>"""


def render_prob_table(data_by_year, title_extra="", use_classes=True):
    """Render a 5-window × 5-year × 2 (imb/da) probability table.

    data_by_year[year][window] = {"imb": x, "da": y}
    """
    rows = []
    for window in ["24h", "72h", "7d", "14d", "21d", "50d"]:
        cells = [f"<td>{window}</td>"]
        for year in YEARS:
            d = data_by_year.get(year, {}).get(window, {}) or {}
            imb = d.get("imb")
            da = d.get("da")
            imb_cls = 'class="val-imb"' if use_classes else ""
            da_cls = 'class="val-da"' if use_classes else ""
            cells.append(f'<td {imb_cls}>{fmt_pct(imb)}</td><td {da_cls}>{fmt_pct(da)}</td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return "\n".join(rows)


def page_1(results):
    # --- Section: Longest continuous negative return (producer baseload) ---
    longest_rows = "\n".join(
        render_period_row(y, results[y].get("longest_negative"), None)
        for y in YEARS
    )
    # --- Section: Max single-period loss baseload ---
    max_loss_rows = "\n".join(
        render_period_row(y, results[y].get("max_loss_baseload"), None)
        for y in YEARS
    )
    # --- Section: Max single-period loss — solar ---
    solar_loss_rows = "\n".join(
        render_period_row(y, results[y].get("max_loss_solar"), None)
        for y in YEARS
    )
    # --- Section: Longest negative return — solar (interval-level) ---
    longest_neg_solar_rows = "\n".join(
        render_period_row(y, results[y].get("longest_neg_solar"), None)
        for y in YEARS
    )
    # --- Section: Worst 24h consumer ---
    worst24h_rows = "\n".join(
        render_worst_24h_row(y, results[y].get("worst_24h_consumer"))
        for y in YEARS
    )
    # --- Section: Worst consumer cost for 72h, 7d, 14d, 21d ---
    worst_cost_tables = {}
    for wname, wlabel in [("72h", "72-Hour"), ("7d", "7-Day"), ("14d", "14-Day"), ("21d", "21-Day"), ("50d", "50-Day")]:
        worst_cost_tables[wname] = "\n".join(
            render_worst_cost_row(y, (results[y].get("worst_consumer") or {}).get(wname))
            for y in YEARS
        )
    # --- Section: Probability of negative return (baseload) ---
    base_prob_data = {y: results[y]["baseload_neg_prob"] for y in YEARS}
    baseload_prob_rows = render_prob_table(base_prob_data)
    # --- Section: Imb vs DA during neg windows ---
    ivd_rows = []
    for window in ["24h", "72h", "7d", "14d", "21d", "50d"]:
        cells = [f"<td>{window}</td>"]
        for year in YEARS:
            d = results[year]["imb_vs_da_during_neg"].get(window)
            if d is None or d.get("never_neg"):
                cells.append('<td><span style="font-size:10px;color:#9ca3af">— never neg —</span></td>')
            else:
                imb = int(round(d["imb_avg"]))
                da = int(round(d["da_avg"]))
                delta = int(round(d["delta"]))
                cells.append(
                    f'<td><span style="font-size:10px;color:#6b7280">imb {imb:+d} / DA {da:+d}</span>'
                    f'<br><span class="val-diff-neg" style="font-size:11px">Δ {delta:+d}/MWh</span></td>'
                )
        ivd_rows.append(f"<tr>{''.join(cells)}</tr>")
    ivd_html = "\n".join(ivd_rows)

    # --- Section: Annual average price comparison ---
    annual_rows = []
    for y in YEARS:
        a = results[y]["annual"]
        diff = a["imb_pos_avg"] - a["da_avg"]
        diff_cls = "val-diff-pos" if diff <= 0 else "val-diff-neg"
        annual_rows.append(f"""<tr>
          <td>{y}</td>
          <td class="val-imb">{fmt_num(a['imb_pos_avg'])}</td>
          <td class="val-da">{fmt_num(a['da_avg'])}</td>
          <td class="{diff_cls}">{diff:+.2f}</td>
          <td>{fmt_int(a['imb_total_baseload'])}</td>
          <td>{fmt_int(a['da_total_baseload'])}</td>
        </tr>""")
    annual_html = "\n".join(annual_rows)

    return f"""
<div class="container page page-3">

  <div class="header">
    <h1>France — Imbalance vs Day-Ahead</h1>
    <p>Same analysis, French market — RTE imbalance settlement vs EPEX day-ahead (FR bidding zone)</p>
  </div>

  <div class="legend">
    <div class="legend-item"><div class="legend-swatch" style="background:#ff6600"></div> Imbalance Price (Prix des Ecarts)</div>
    <div class="legend-item"><div class="legend-swatch" style="background:#3c3c3c"></div> Day-Ahead Price (FR)</div>
  </div>

  <div class="coverage">
    <div class="coverage-item">
      <h4>Time Period</h4>
      <p><strong>2021-01-01 to 2025-12-31</strong><br>5 full years</p>
    </div>
    <div class="coverage-item">
      <h4>Day-Ahead Source</h4>
      <p><strong>ENTSO-E 12.1.D</strong><br>FR bidding zone, hourly</p>
    </div>
    <div class="coverage-item">
      <h4>Imbalance Source</h4>
      <p><strong>RTE Prix des Ecarts Positifs</strong><br>30-min (2021–24) / 15-min (2025+)</p>
    </div>
  </div>

  <div class="section-title"><span class="dot"></span> Producer (Injection): Longest Continuous Negative Return</div>
  <div class="summary-section"><div class="summary-wrap">
    <table>
      <thead><tr>
        <th>Year</th><th>Period</th><th>Duration</th>
        <th>Imbalance<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Day-Ahead<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Difference<br><span style="font-weight:400">EUR/MWh (total)</span></th>
      </tr></thead>
      <tbody>
{longest_rows}
      </tbody>
    </table>
    <div style="text-align:center;font-size:11px;color:#9ca3af;margin-top:12px">Average EUR/MWh and total EUR for 1 MW asset over the period</div>
  </div></div>

  <div class="section-title"><span class="dot"></span> Producer: Maximum Single-Period Loss (Deepest Drawdown)</div>
  <div class="summary-section"><div class="summary-wrap">
    <table>
      <thead><tr>
        <th>Year</th><th>Period</th><th>Duration</th>
        <th>Imbalance<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Day-Ahead<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Difference<br><span style="font-weight:400">EUR/MWh (total)</span></th>
      </tr></thead>
      <tbody>
{max_loss_rows}
      </tbody>
    </table>
    <div style="text-align:center;font-size:11px;color:#9ca3af;margin-top:12px">Average EUR/MWh and total EUR for 1 MW asset over the period</div>
  </div></div>

  <div class="section-title"><span class="dot"></span> Producer: Maximum Single-Period Loss — Solar (1 MW Daylight Only, Paris 48.85°N)</div>
  <div class="summary-section"><div class="summary-wrap">
    <p style="font-size:12px;color:#6b7280;margin-bottom:16px">Same methodology as baseload, but only daylight intervals (Paris latitude, NOAA solar algorithm) contribute to the return. Night intervals = zero. Day-ahead comparison uses the same daylight hours.</p>
    <table>
      <thead><tr>
        <th>Year</th><th>Period</th><th>Daylight Hours</th>
        <th>Imbalance<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Day-Ahead<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Difference<br><span style="font-weight:400">EUR/MWh (total)</span></th>
      </tr></thead>
      <tbody>
{solar_loss_rows}
      </tbody>
    </table>
    <div style="text-align:center;font-size:11px;color:#9ca3af;margin-top:12px">Average EUR/MWh and total EUR for 1 MW solar asset.</div>
  </div></div>

  <div class="section-title"><span class="dot"></span> Producer: Longest Continuous Negative Return — Solar (1 MW Daylight Only, Paris 48.85°N)</div>
  <div class="summary-section"><div class="summary-wrap">
    <p style="font-size:12px;color:#6b7280;margin-bottom:16px">Longest contiguous span of daylight intervals where the cumulative solar return was negative. Only daylight intervals contribute; night intervals are excluded.</p>
    <table>
      <thead><tr>
        <th>Year</th><th>Period</th><th>Daylight Hours</th>
        <th>Imbalance<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Day-Ahead<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Difference<br><span style="font-weight:400">EUR/MWh (total)</span></th>
      </tr></thead>
      <tbody>
{longest_neg_solar_rows}
      </tbody>
    </table>
    <div style="text-align:center;font-size:11px;color:#9ca3af;margin-top:12px">Average EUR/MWh and total EUR for 1 MW solar asset over the period.</div>
  </div></div>

  <div class="section-title"><span class="dot"></span> Consumer: Worst 24-Hour Cost (Most Expensive Day) — Imbalance values use Prix Négatif</div>
  <div class="summary-section"><div class="summary-wrap">
    <p style="font-size:12px;color:#6b7280;margin-bottom:16px">Consumer cost uses <strong>Prix des Ecarts Négatifs</strong> (the imbalance price applied to under-deliveries / consumption above nomination) — the French analogue of NL Price Shortage.</p>
    <table>
      <thead><tr>
        <th>Year</th><th>Date</th>
        <th>Imbalance (Négatif)<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Day-Ahead<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Difference<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Premium</th>
      </tr></thead>
      <tbody>
{worst24h_rows}
      </tbody>
    </table>
    <div style="text-align:center;font-size:11px;color:#9ca3af;margin-top:12px">Average EUR/MWh and total EUR for 1 MW flat consumption over the day</div>
  </div></div>

  <div class="section-title"><span class="dot"></span> Consumer: Worst 72-Hour Cost — Imbalance values use Prix Négatif</div>
  <div class="summary-section"><div class="summary-wrap">
    <table>
      <thead><tr>
        <th>Year</th><th>Period</th>
        <th>Imbalance (Négatif)<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Day-Ahead<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Difference<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Premium</th>
      </tr></thead>
      <tbody>
{worst_cost_tables["72h"]}
      </tbody>
    </table>
  </div></div>

  <div class="section-title"><span class="dot"></span> Consumer: Worst 7-Day Cost — Imbalance values use Prix Négatif</div>
  <div class="summary-section"><div class="summary-wrap">
    <table>
      <thead><tr>
        <th>Year</th><th>Period</th>
        <th>Imbalance (Négatif)<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Day-Ahead<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Difference<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Premium</th>
      </tr></thead>
      <tbody>
{worst_cost_tables["7d"]}
      </tbody>
    </table>
  </div></div>

  <div class="section-title"><span class="dot"></span> Consumer: Worst 14-Day Cost — Imbalance values use Prix Négatif</div>
  <div class="summary-section"><div class="summary-wrap">
    <table>
      <thead><tr>
        <th>Year</th><th>Period</th>
        <th>Imbalance (Négatif)<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Day-Ahead<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Difference<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Premium</th>
      </tr></thead>
      <tbody>
{worst_cost_tables["14d"]}
      </tbody>
    </table>
  </div></div>

  <div class="section-title"><span class="dot"></span> Consumer: Worst 21-Day Cost — Imbalance values use Prix Négatif</div>
  <div class="summary-section"><div class="summary-wrap">
    <table>
      <thead><tr>
        <th>Year</th><th>Period</th>
        <th>Imbalance (Négatif)<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Day-Ahead<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Difference<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Premium</th>
      </tr></thead>
      <tbody>
{worst_cost_tables["21d"]}
      </tbody>
    </table>
  </div></div>

  <div class="section-title"><span class="dot"></span> Consumer: Worst 50-Day Cost — Imbalance values use Prix Négatif</div>
  <div class="summary-section"><div class="summary-wrap">
    <table>
      <thead><tr>
        <th>Year</th><th>Period</th>
        <th>Imbalance (Négatif)<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Day-Ahead<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Difference<br><span style="font-weight:400">EUR/MWh (total)</span></th>
        <th>Premium</th>
      </tr></thead>
      <tbody>
{worst_cost_tables["50d"]}
      </tbody>
    </table>
  </div></div>

  <div class="section-title"><span class="dot"></span> Probability of Negative Return — Imbalance vs Day-Ahead (1 MW Baseload)</div>
  <div class="summary-section"><div class="summary-wrap">
    <p style="font-size:12px;color:#6b7280;margin-bottom:16px">% of rolling windows in which a 1 MW baseload injection asset produced a negative return on each market.</p>
    <table>
      <thead>
        <tr>
          <th>Window</th>
          <th colspan="2">2021</th><th colspan="2">2022</th><th colspan="2">2023</th><th colspan="2">2024</th><th colspan="2">2025</th>
        </tr>
        <tr>
          <th></th>
          <th style="font-size:10px;color:#ff6600">Imb</th><th style="font-size:10px">DA</th>
          <th style="font-size:10px;color:#ff6600">Imb</th><th style="font-size:10px">DA</th>
          <th style="font-size:10px;color:#ff6600">Imb</th><th style="font-size:10px">DA</th>
          <th style="font-size:10px;color:#ff6600">Imb</th><th style="font-size:10px">DA</th>
          <th style="font-size:10px;color:#ff6600">Imb</th><th style="font-size:10px">DA</th>
        </tr>
      </thead>
      <tbody>
{baseload_prob_rows}
      </tbody>
    </table>
  </div></div>

  <div class="section-title"><span class="dot"></span> Imbalance vs Day-Ahead During Imbalance Negative-Return Windows</div>
  <div class="summary-section"><div class="summary-wrap">
    <p style="font-size:12px;color:#6b7280;margin-bottom:16px">When the imbalance produced a negative return, what was the simultaneous day-ahead price? Difference shows the gap (EUR/MWh) you would have avoided by trading day-ahead.</p>
    <table>
      <thead><tr>
        <th>Window</th><th>2021</th><th>2022</th><th>2023</th><th>2024</th><th>2025</th>
      </tr></thead>
      <tbody>
{ivd_html}
      </tbody>
    </table>
  </div></div>

  <div class="section-title"><span class="dot"></span> Annual Average Price Comparison</div>
  <div class="summary-section"><div class="summary-wrap">
    <table>
      <thead><tr>
        <th>Year</th><th>Imbalance Avg (Pos)</th><th>Day-Ahead Avg</th><th>Difference</th>
        <th>Annual Total Imbalance<br><span style="font-weight:400">(1 MW baseload)</span></th>
        <th>Annual Total Day-Ahead<br><span style="font-weight:400">(1 MW baseload)</span></th>
      </tr></thead>
      <tbody>
{annual_html}
      </tbody>
    </table>
    <div style="text-align:center;font-size:11px;color:#9ca3af;margin-top:12px">EUR/MWh and total EUR per year. Imbalance values are Prix des Ecarts Positifs (producer baseload).</div>
  </div></div>

  <div class="footer">
    Day-ahead from ENTSO-E (12.1.D, FR bidding zone) | Imbalance from RTE (Prix des Ecarts Positifs/Négatifs) | 2021-01-01 to 2025-12-31
  </div>
</div>
<!-- END PAGE 3 (FR) -->
"""


def page_2(results):
    # Producer baseload
    base = render_prob_table({y: results[y]["baseload_neg_prob"] for y in YEARS})
    # Producer solar
    solar = render_prob_table({y: results[y]["solar_neg_prob"] for y in YEARS})

    # Consumer flat/res at thresholds — need to flatten the {"imb": {..}, "da": {..}} structure
    def flatten_cons(year_key, threshold_key):
        out = {}
        for y in YEARS:
            src = results[y][threshold_key]
            out[y] = {
                w: {"imb": src["imb"].get(w), "da": src["da"].get(w)}
                for w in ["24h", "72h", "7d", "14d", "21d", "50d"]
            }
        return out

    flat_100 = render_prob_table(flatten_cons(None, "consumer_flat_over_100"))
    flat_150 = render_prob_table(flatten_cons(None, "consumer_flat_over_150"))
    res_100 = render_prob_table(flatten_cons(None, "consumer_res_over_100"))
    res_150 = render_prob_table(flatten_cons(None, "consumer_res_over_150"))

    # Expensive periods
    exp_imb_rows = []
    exp_da_rows = []
    for y in YEARS:
        ei = results[y].get("expensive_period_on_imbalance")
        ed = results[y].get("expensive_period_on_da")
        if ei:
            exp_imb_rows.append(
                f"<tr><td>{y}</td><td style='font-size:11px'>{ei['date']}</td>"
                f"<td class='val-imb'>{fmt_int(ei['imb_avg'])}<br><span style='font-size:11px;font-weight:400'>({fmt_int(ei['imb_total'])})</span></td>"
                f"<td class='val-da'>{fmt_int(ei['da_avg'])}</td>"
                f"<td class='val-diff-neg'>{int(ei['imb_avg'] - ei['da_avg']):+d}</td></tr>"
            )
        if ed:
            exp_da_rows.append(
                f"<tr><td>{y}</td><td style='font-size:11px'>{ed['date']}</td>"
                f"<td class='val-imb'>{fmt_int(ed['imb_avg'])}</td>"
                f"<td class='val-da'>{fmt_int(ed['da_avg'])}<br><span style='font-size:11px;font-weight:400'>({fmt_int(ed['da_total'])})</span></td>"
                f"<td class='val-diff-pos'>{int(ed['imb_avg'] - ed['da_avg']):+d}</td></tr>"
            )
    exp_imb_html = "\n".join(exp_imb_rows)
    exp_da_html = "\n".join(exp_da_rows)

    def prob_table_block(title, body, note=""):
        note_html = f'<div style="text-align:center;font-size:11px;color:#9ca3af;margin-top:12px">{note}</div>' if note else ""
        return f"""
    <div class="section-title"><span class="dot"></span> {title}</div>
    <div class="summary-section"><div class="summary-wrap">
      <table>
        <thead>
          <tr>
            <th>Window</th>
            <th colspan="2">2021</th><th colspan="2">2022</th><th colspan="2">2023</th><th colspan="2">2024</th><th colspan="2">2025</th>
          </tr>
          <tr>
            <th></th>
            <th style="font-size:10px;color:#ff6600">Imb</th><th style="font-size:10px">DA</th>
            <th style="font-size:10px;color:#ff6600">Imb</th><th style="font-size:10px">DA</th>
            <th style="font-size:10px;color:#ff6600">Imb</th><th style="font-size:10px">DA</th>
            <th style="font-size:10px;color:#ff6600">Imb</th><th style="font-size:10px">DA</th>
            <th style="font-size:10px;color:#ff6600">Imb</th><th style="font-size:10px">DA</th>
          </tr>
        </thead>
        <tbody>
{body}
        </tbody>
      </table>
      {note_html}
    </div></div>
"""

    return f"""
<div class="container page page-4">
  <div>
    <div class="header">
      <h1>France — Profile-Specific Comparison</h1>
      <p>Probability of negative return — Imbalance vs Day-Ahead — across producer and consumer profiles</p>
    </div>

    <div class="legend">
      <div class="legend-item"><div class="legend-swatch" style="background:#ff6600"></div> Imbalance</div>
      <div class="legend-item"><div class="legend-swatch" style="background:#3c3c3c"></div> Day-Ahead</div>
    </div>

    <div class="coverage" style="grid-template-columns: 1fr 1fr">
      <div class="coverage-item">
        <h4>Producer Profiles</h4>
        <p><strong>Baseload:</strong> 1 MW constant injection, 24/7<br>
        <strong>Solar:</strong> 1 MW only when sun is up (Paris 48.85°N, NOAA solar algorithm)</p>
      </div>
      <div class="coverage-item">
        <h4>Consumer Profiles</h4>
        <p><strong>Flat:</strong> 1 MW constant consumption, 24/7<br>
        <strong>Residential:</strong> Enedis RES1-style profile — weaker morning peak, lunch bump, strong evening peak, winter +55% (heavy electric heating)</p>
      </div>
    </div>

{prob_table_block("Producer — Baseload (1 MW 24/7): % Negative Return", base)}
{prob_table_block("Producer — Solar (1 MW Daylight Only): % Negative Return", solar, "Solar is more exposed to midday surplus: French solar growth depresses daytime prices.")}
{prob_table_block("Consumer — Flat (1 MW 24/7): % of Periods with Average Price > 100 EUR/MWh (Imbalance = Prix Négatif)", flat_100)}
{prob_table_block("Consumer — Residential Profile: % of Periods with Average Price > 100 EUR/MWh (Imbalance = Prix Négatif)", res_100)}
{prob_table_block("Consumer — Flat (1 MW 24/7): % of Periods with Average Price > 150 EUR/MWh (Imbalance = Prix Négatif)", flat_150)}
{prob_table_block("Consumer — Residential Profile: % of Periods with Average Price > 150 EUR/MWh (Imbalance = Prix Négatif)", res_150)}

    <div class="section-title"><span class="dot"></span> Consumer — Most Expensive Periods Identified on <span style="color:#ff6600">Imbalance (Prix Négatif)</span></div>
    <div class="summary-section"><div class="summary-wrap">
      <table>
        <thead><tr>
          <th>Year</th><th>Date</th>
          <th>Imbalance Avg<br><span style="font-weight:400">EUR/MWh (day total)</span></th>
          <th>Day-Ahead Avg</th>
          <th>Δ (Imb − DA)</th>
        </tr></thead>
        <tbody>
{exp_imb_html}
        </tbody>
      </table>
    </div></div>

    <div class="section-title"><span class="dot"></span> Consumer — Most Expensive Periods Identified on <span style="color:#3c3c3c">Day-Ahead</span></div>
    <div class="summary-section"><div class="summary-wrap">
      <table>
        <thead><tr>
          <th>Year</th><th>Date</th>
          <th>Imbalance Avg</th>
          <th>Day-Ahead Avg<br><span style="font-weight:400">EUR/MWh (day total)</span></th>
          <th>Δ (Imb − DA)</th>
        </tr></thead>
        <tbody>
{exp_da_html}
        </tbody>
      </table>
    </div></div>
  </div>

  <div class="footer">
    French market analysis — RTE imbalance settlement (Prix des Ecarts) + ENTSO-E day-ahead (FR) | 2021–2025
  </div>
</div>
<!-- END PAGE 4 (FR) -->
"""


def main():
    with open(RESULTS) as f:
        results = json.load(f)
    html = page_1(results) + "\n" + page_2(results)
    with open(OUT, "w") as f:
        f.write(html)
    print(f"Wrote {OUT} ({len(html)} chars)")


if __name__ == "__main__":
    main()
