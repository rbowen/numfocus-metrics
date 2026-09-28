#!/usr/bin/env python3
"""
NumFOCUS Series — multi-page HTML dashboard generator.

Reads data.json and produces:
  dashboard/index.html        — overview with charts
  dashboard/project-{name}.html — per-project pages
  dashboard/company-{name}.html — per-company pages
  dashboard/about.html        — data API docs
  dashboard/data.json         — raw data
  dashboard/summary.json      — aggregated stats
  dashboard/participants.json — roster

Usage:  uv run --no-project python generate_dashboard.py
"""

import json, sys, shutil
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from collections import defaultdict, Counter

BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "data.json"
OUTPUT_DIR = BASE_DIR / "dashboard"

COLORS = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff",
          "#f778ba", "#79c0ff", "#56d364", "#e3b341", "#ffa198"]

# ─── Shared HTML ─────────────────────────────────────────────────────────────

CSS = """
:root { --bg:#0d1117; --surface:#161b22; --surface2:#1c2333; --border:#30363d;
        --text:#e6edf3; --muted:#8b949e; --accent:#58a6ff;
        --green:#3fb950; --orange:#d29922; --red:#f85149; --purple:#bc8cff; }
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,sans-serif;background:var(--bg);color:var(--text);line-height:1.6}
.container{max-width:1200px;margin:0 auto;padding:20px}
a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}
header{text-align:center;padding:24px 0 16px;border-bottom:1px solid var(--border);margin-bottom:20px}
header h1{font-size:1.6em;margin-bottom:2px} header p{color:var(--muted);font-size:0.85em}
nav.topnav{display:flex;gap:6px;justify-content:center;flex-wrap:wrap;margin:16px 0 20px}
nav.topnav a{padding:6px 14px;border-radius:6px;background:var(--surface);border:1px solid var(--border);
             font-size:0.85em;color:var(--muted);white-space:nowrap}
nav.topnav a.active{background:var(--accent);color:#000;font-weight:600;border-color:var(--accent)}
nav.topnav a:hover{background:var(--surface2);text-decoration:none}
.dropdown{position:relative;display:inline-block}
.dropdown>a{cursor:pointer}
.dropdown-menu{display:none;position:absolute;top:100%;left:0;background:var(--surface);border:1px solid var(--border);
               border-radius:6px;padding:4px;z-index:100;min-width:120px;margin-top:2px;box-shadow:0 4px 12px rgba(0,0,0,0.3)}
.dropdown-menu a{display:block;margin:2px 0;text-align:left}
.dropdown:hover .dropdown-menu{display:block}
.cards{display:flex;gap:14px;justify-content:center;flex-wrap:wrap;margin:16px 0}
.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px 20px;text-align:center;min-width:100px}
.card .n{font-size:1.8em;font-weight:700;color:var(--accent)} .card .l{color:var(--muted);font-size:0.8em}
.section{margin:28px 0} .section h2{font-size:1.2em;margin-bottom:10px;border-bottom:1px solid var(--border);padding-bottom:6px}
.row{display:flex;gap:20px;flex-wrap:wrap;margin:16px 0}
.box{flex:1;min-width:280px;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px}
.box h3{font-size:0.95em;color:var(--muted);margin-bottom:10px}
table.t{width:100%;border-collapse:collapse;font-size:0.85em}
table.t th{text-align:left;padding:8px;border-bottom:2px solid var(--border);color:var(--muted)}
table.t td{padding:6px 8px;border-bottom:1px solid var(--border)}
table.t tr:hover{background:rgba(88,166,255,0.05)}
.badge{padding:2px 8px;border-radius:12px;font-size:0.78em;font-weight:600;display:inline-block}
.b-pr{background:rgba(63,185,80,0.15);color:var(--green)} .b-commit{background:rgba(88,166,255,0.15);color:var(--accent)}
.b-issue{background:rgba(210,153,34,0.15);color:var(--orange)} .b-comment{background:rgba(139,148,158,0.15);color:var(--muted)}
.b-review{background:rgba(188,140,255,0.15);color:var(--purple)}
.merged{color:var(--green);font-size:0.78em;margin-left:4px}
.co{font-size:0.72em;color:var(--muted);background:var(--surface2);padding:1px 5px;border-radius:3px;margin-left:3px}
.empty{color:var(--muted);font-style:italic;padding:16px;text-align:center}
.warn{background:rgba(248,81,73,0.1);border:1px solid var(--red);border-radius:8px;padding:10px 14px;margin:14px 0;font-size:0.88em}
.bar-chart{display:flex;flex-direction:column;gap:5px}
.bar-row{display:flex;align-items:center;gap:6px}
.bar-label{width:90px;font-size:0.82em;text-align:right;color:var(--muted);overflow:hidden;white-space:nowrap}
.bar-fill{height:20px;border-radius:3px;min-width:2px;transition:width .3s}
.bar-val{font-size:0.78em;color:var(--muted);margin-left:4px;min-width:24px}
.bar-chart-stacked{gap:9px}
.bar-stack{display:flex;flex-direction:column;gap:2px}
.bar-stack-label{font-size:0.82em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:flex;align-items:baseline}
.bar-stack-label .bar-val{margin-left:auto;padding-left:8px}
.bar-track{width:100%}
.bar-track .bar-fill{width:100%}
.donut-wrap{display:flex;justify-content:center;align-items:center;gap:16px}
.donut-legend{font-size:0.82em} .donut-legend div{margin:2px 0;display:flex;align-items:center;gap:5px}
.swatch{width:10px;height:10px;border-radius:2px;display:inline-block}
.tl{display:flex;align-items:flex-end;gap:2px;height:110px;padding-top:8px}
.tl-bar{flex:1;background:var(--accent);border-radius:2px 2px 0 0;min-width:5px;position:relative;transition:height .3s}
.tl-bar:hover{opacity:.8} .tl-bar .tip{display:none;position:absolute;bottom:100%;left:50%;transform:translateX(-50%);
  background:var(--surface);border:1px solid var(--border);padding:3px 7px;border-radius:4px;font-size:.72em;white-space:nowrap;z-index:10}
.tl-bar:hover .tip{display:block}
.tl-labels{display:flex;gap:2px;margin-top:3px}
.tl-labels span{flex:1;text-align:center;font-size:.6em;color:var(--muted)}
footer{text-align:center;color:var(--muted);font-size:.78em;padding:24px 0 8px;border-top:1px solid var(--border);margin-top:32px}
pre.json{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px;overflow-x:auto;font-size:.83em}
"""


def nav(active, projects, companies):
    proj_items = "".join(
        f'<a href="project-{p.lower().replace(" ","-")}.html"'
        f' class="{"active" if f"project-{p.lower().replace(" ","-")}.html"==active else ""}">{p}</a>'
        for p in projects)
    co_items = "".join(
        f'<a href="company-{c.lower().replace(" ","-")}.html"'
        f' class="{"active" if f"company-{c.lower().replace(" ","-")}.html"==active else ""}">{c}</a>'
        for c in companies)
    ov_cls = "active" if active=="index.html" else ""
    ab_cls = "active" if active=="about.html" else ""
    proj_active = any(f"project-{p.lower().replace(' ','-')}.html"==active for p in projects)
    co_active = any(f"company-{c.lower().replace(' ','-')}.html"==active for c in companies)
    return f'''<nav class="topnav">
        <a href="index.html" class="{ov_cls}">Overview</a>
        <div class="dropdown">
            <a class="{"active" if proj_active else ""}">Projects ▾</a>
            <div class="dropdown-menu">{proj_items}</div>
        </div>
        <div class="dropdown">
            <a class="{"active" if co_active else ""}">Companies ▾</a>
            <div class="dropdown-menu">{co_items}</div>
        </div>
        <a href="about.html" class="{ab_cls}">Data API</a>
    </nav>'''


def page_wrap(title, subtitle, active, body, projects, companies, collected_at):
    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{CSS}</style></head><body>
<div class="container">
<header><h1>🐼🔢🧪⚡🕸️ {title}</h1><p>{subtitle}</p>
<p style="font-size:0.8em;color:var(--muted)">Updated: {collected_at[:16].replace("T"," ")} UTC</p></header>
{nav(active, projects, companies)}
{body}
<footer>NumFOCUS Sustaining Open Source Series — Fall 2026 ·
<a href="data.json">data.json</a> · <a href="summary.json">summary.json</a></footer>
</div></body></html>'''


# ─── Chart helpers ───────────────────────────────────────────────────────────

# Fixed employer -> color mapping (kept stable so the legend is meaningful).
EMPLOYER_COLORS = {"AWS": "#d29922", "Bloomberg": "#58a6ff", "NVIDIA": "#3fb950"}
EMPLOYER_FALLBACK = "#8b949e"  # --muted, for Unknown/other


def category_legend(categories, color_map, default_color=EMPLOYER_FALLBACK):
    """Inline swatch+label legend for the given categories, in order."""
    if not categories: return ""
    swatches = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px">'
        f'<span class="swatch" style="background:{color_map.get(c, default_color)}"></span>'
        f'{c}</span>'
        for c in categories)
    return f'<div style="margin-top:10px;font-size:0.8em;color:var(--muted)">{swatches}</div>'


def bar_chart(triples, color_map=None, default_color=EMPLOYER_FALLBACK,
              show_legend=True, max_val=None):
    """Left-aligned stacked bar chart (label+count row, full-width bar below).

    triples: list of (label, value, category). For charts with no category
        distinction, pass category=None (or the label) — colors then cycle
        through the palette per row and no legend is shown.
    color_map: category -> hex color. When given, each bar is colored by its
        category and (unless show_legend=False) a legend of the categories
        present is appended. When None, colors cycle through COLORS per row.
    show_legend: set False to suppress the legend even with a color_map (e.g.
        when the bar labels already are the category names).
    """
    if not triples: return '<p class="empty">No data</p>'
    if max_val is None: max_val = max(v for _,v,_ in triples) or 1
    seen = []
    rows = []
    for i,(label,val,cat) in enumerate(triples):
        pct = val/max_val*100 if max_val else 0
        if color_map is not None:
            color = color_map.get(cat, default_color)
            label_style = f' style="color:{color};font-weight:600"'
            if cat not in seen: seen.append(cat)
        else:
            color = COLORS[i%len(COLORS)]
            label_style = ""
        rows.append(f'<div class="bar-stack">'
                    f'<div class="bar-stack-label"{label_style}>{label}'
                    f'<span class="bar-val">{val}</span></div>'
                    f'<div class="bar-track"><div class="bar-fill" '
                    f'style="width:{max(pct,1):.0f}%;background:{color}"></div></div></div>')
    chart = f'<div class="bar-chart bar-chart-stacked">{"".join(rows)}</div>'
    if color_map is None or not show_legend:
        return chart
    return chart + category_legend(seen, color_map, default_color)


def donut(pairs, size=130):
    total = sum(v for _,v in pairs) or 1
    segs, offset, r, cx = [], 0, 45, 55
    circ = 2*3.14159*r
    for i,(label,val) in enumerate(pairs):
        dash = val/total*circ
        gap = circ-dash
        c = COLORS[i%len(COLORS)]
        segs.append(f'<circle r="{r}" cx="{cx}" cy="{cx}" fill="none" stroke="{c}" '
                    f'stroke-width="18" stroke-dasharray="{dash:.1f} {gap:.1f}" stroke-dashoffset="{-offset:.1f}"/>')
        offset += dash
    svg = (f'<svg width="{size}" height="{size}" viewBox="0 0 110 110">'
           f'<circle r="{r}" cx="{cx}" cy="{cx}" fill="none" stroke="var(--border)" stroke-width="18"/>'
           f'{"".join(segs)}'
           f'<text x="{cx}" y="{cx}" text-anchor="middle" dy=".35em" fill="var(--text)" font-size="15" font-weight="700">{total}</text></svg>')
    legend = "".join(f'<div><span class="swatch" style="background:{COLORS[i%len(COLORS)]}"></span>'
                     f'{l}: {v} ({v/total*100:.0f}%)</div>' for i,(l,v) in enumerate(pairs))
    return f'<div class="donut-wrap">{svg}<div class="donut-legend">{legend}</div></div>'


def timeline(activity):
    if not activity: return '<p class="empty">No activity yet</p>'
    dates = Counter()
    for item in activity:
        d = (item.get("created_at") or item.get("submitted_at") or "")[:10]
        if d: dates[d] += 1
    if not dates: return '<p class="empty">No dated activity</p>'
    sd = sorted(dates.keys())
    start = date.fromisoformat(sd[0]); end = date.fromisoformat(sd[-1])
    days = []; d = start
    while d <= end:
        ds = d.isoformat(); days.append((ds, dates.get(ds,0))); d += timedelta(days=1)
    mx = max(v for _,v in days) or 1
    bars = "".join(f'<div class="tl-bar" style="height:{max(v/mx*100,1):.0f}%"><div class="tip">{ds}: {v}</div></div>'
                   for ds,v in days)
    labels = "".join(f'<span>{ds[5:] if i%7==0 else ""}</span>' for i,(ds,_) in enumerate(days))
    return f'<div class="tl">{bars}</div><div class="tl-labels">{labels}</div>'


# ─── Table helpers ───────────────────────────────────────────────────────────

def activity_table(items, limit=200):
    if not items: return '<p class="empty">No activity yet.</p>'
    rows = []
    for item in items[:limit]:
        t = item["type"]
        d = (item.get("created_at") or item.get("submitted_at") or "")[:10]
        who = item.get("person_name", item.get("author","?"))
        co = item.get("company","?")
        title = (item.get("title") or item.get("body_preview") or item.get("pr_title") or "")[:80]
        url = item.get("url") or item.get("issue_url") or "#"
        bcls = {"pr":"b-pr","issue":"b-issue","comment":"b-comment","review":"b-review","commit":"b-commit"}.get(t,"")
        mg = ' <span class="merged">✓merged</span>' if item.get("merged") else ""
        rows.append(f'<tr><td>{d}</td><td><span class="badge {bcls}">{t}</span>{mg}</td>'
                    f'<td>{who}<span class="co">{co}</span></td>'
                    f'<td><a href="{url}" target="_blank">{title}</a></td><td>{item.get("state","")}</td></tr>')
    return (f'<table class="t"><thead><tr><th>Date</th><th>Type</th><th>Person</th>'
            f'<th>Title</th><th>State</th></tr></thead><tbody>{"".join(rows)}</tbody></table>')


def leaderboard(items, participants):
    stats = defaultdict(lambda: {"prs":0,"merged":0,"commits":0,"issues":0,"comments":0,"reviews":0,"total":0})
    for item in items:
        a = item.get("author","").lower(); t = item["type"]
        stats[a]["total"] += 1
        if t=="pr": stats[a]["prs"]+=1; stats[a]["merged"]+=int(bool(item.get("merged")))
        elif t=="commit": stats[a]["commits"]+=1
        elif t=="issue": stats[a]["issues"]+=1
        elif t=="comment": stats[a]["comments"]+=1
        elif t=="review": stats[a]["reviews"]+=1
    if not stats: return '<p class="empty">No activity yet.</p>'
    rows = []
    seen = []
    for i,(gh,s) in enumerate(sorted(stats.items(),key=lambda x:x[1]["total"],reverse=True),1):
        info = participants.get(gh,{})
        nm = info.get("name",gh); co = info.get("company","?")
        color = EMPLOYER_COLORS.get(co, EMPLOYER_FALLBACK)
        if co not in seen: seen.append(co)
        rows.append(f'<tr><td>{i}</td><td><span style="color:{color};font-weight:600">{nm}</span>'
                    f'<span class="co">{co}</span></td>'
                    f'<td>{s["prs"]}</td><td>{s["merged"]}</td><td>{s["commits"]}</td>'
                    f'<td>{s["issues"]}</td><td>{s["comments"]}</td><td>{s["reviews"]}</td>'
                    f'<td><strong>{s["total"]}</strong></td></tr>')
    return (f'<table class="t"><thead><tr><th>#</th><th>Person</th><th>PRs</th><th>Merged</th>'
            f'<th>Commits</th><th>Issues</th><th>Comments</th><th>Reviews</th><th>Total</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table>'
            + category_legend(seen, EMPLOYER_COLORS, EMPLOYER_FALLBACK))


def project_matrix(by_project, project_names):
    rows = ""
    for p in project_names:
        items = by_project.get(p,[])
        po = sum(1 for a in items if a["type"]=="pr" and a.get("state")=="open")
        pm = sum(1 for a in items if a["type"]=="pr" and a.get("merged"))
        pc = sum(1 for a in items if a["type"]=="pr" and a.get("state")=="closed" and not a.get("merged"))
        cm = sum(1 for a in items if a["type"]=="commit")
        iss = sum(1 for a in items if a["type"]=="issue")
        co = sum(1 for a in items if a["type"]=="comment")
        rv = sum(1 for a in items if a["type"]=="review")
        slug = p.lower().replace(" ","-")
        rows += (f'<tr><td><a href="project-{slug}.html">{p}</a></td><td>{po}</td><td>{pm}</td>'
                 f'<td>{pc}</td><td>{cm}</td><td>{iss}</td><td>{co}</td><td>{rv}</td>'
                 f'<td><strong>{len(items)}</strong></td></tr>')
    return (f'<table class="t"><thead><tr><th>Project</th><th>PRs Open</th><th>PRs Merged</th>'
            f'<th>PRs Closed</th><th>Commits</th><th>Issues</th><th>Comments</th><th>Reviews</th>'
            f'<th>Total</th></tr></thead><tbody>{rows}</tbody></table>')


def inactive_callout(activity, participants, window_days=7):
    # "Active" = authored at least one activity in the trailing window_days,
    # measured back from the current wall-clock time.
    ref = datetime.now(tz=timezone.utc)
    cutoff = ref - timedelta(days=window_days)

    def _dt(item):
        raw = item.get("created_at") or item.get("submitted_at") or ""
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    active = set()
    for a in activity:
        d = _dt(a)
        if d is not None and d >= cutoff:
            active.add(a.get("author", "").lower())

    inactive_keys = [g for g in set(participants) - active if g in participants]
    if not inactive_keys:
        return ""

    # Split by employer.
    by_co = defaultdict(list)
    for g in inactive_keys:
        info = participants[g]
        by_co[info.get("company", "Unknown")].append(info.get("name", g))

    total = len(inactive_keys)
    groups = []
    for co in sorted(by_co, key=lambda c: (-len(by_co[c]), c)):
        names = ", ".join(sorted(by_co[co]))
        groups.append(f'<div style="margin-top:6px"><strong>{co} ({len(by_co[co])}):</strong> {names}</div>')
    return (f'<div class="warn">⚠️ <strong>Inactive (no activity in last {window_days} days) '
            f'({total}):</strong>{"".join(groups)}</div>')


# ─── Page generators ─────────────────────────────────────────────────────────

def load_data():
    data = json.loads(DATA_FILE.read_text())
    activity = data.get("activity",[])
    projects = data.get("projects",{})
    participants = data.get("participants",{})
    companies_config = data.get("companies",{})
    summary = data.get("summary",{})
    collected_at = data.get("collected_at","?")

    r2p = {v["repo"]:k for k,v in projects.items()}
    by_project = defaultdict(list)
    by_company = defaultdict(list)
    for item in activity:
        by_project[r2p.get(item.get("repo",""),"?")].append(item)
        by_company[item.get("company","Unknown")].append(item)

    return dict(activity=activity, projects=projects, participants=participants,
                companies_config=companies_config, summary=summary, collected_at=collected_at,
                by_project=by_project, by_company=by_company)


def gen_index(D):
    s = D["summary"]; act = D["activity"]
    merged = sum(1 for a in act if a.get("merged"))
    active = len(set(a.get("author","").lower() for a in act))
    commits = s.get("commits",0)
    proj_names = list(D["projects"].keys())
    co_names = list(D["companies_config"].keys())

    cards = f'''<div class="cards">
        <div class="card"><div class="n">{s.get("total_activities",0)}</div><div class="l">Activities</div></div>
        <div class="card"><div class="n">{s.get("prs",0)}</div><div class="l">PRs</div></div>
        <div class="card"><div class="n">{merged}</div><div class="l">Merged</div></div>
        <div class="card"><div class="n">{commits}</div><div class="l">Commits</div></div>
        <div class="card"><div class="n">{s.get("issues",0)}</div><div class="l">Issues</div></div>
        <div class="card"><div class="n">{s.get("comments",0)}</div><div class="l">Comments</div></div>
        <div class="card"><div class="n">{s.get("reviews",0)}</div><div class="l">Reviews</div></div>
        <div class="card"><div class="n">{active}</div><div class="l">Active</div></div>
    </div>'''

    tl = f'<div class="section"><h2>Daily Activity</h2>{timeline(act)}</div>'

    type_d = donut([("PRs",s.get("prs",0)),("Commits",commits),
                    ("Issues",s.get("issues",0)),("Comments",s.get("comments",0)),
                    ("Reviews",s.get("reviews",0))])
    proj_b = bar_chart([(p, len(D["by_project"].get(p,[])), None) for p in proj_names])
    co_pairs = sorted(D["by_company"].items(), key=lambda x:-len(x[1]))
    co_b = bar_chart([(c, len(items), c) for c,items in co_pairs],
                     color_map=EMPLOYER_COLORS, show_legend=False)

    person_totals = Counter()
    for item in act: person_totals[item.get("author","").lower()] += 1
    top10 = [(D["participants"].get(g,{}).get("name",g), c,
              D["participants"].get(g,{}).get("company","Unknown"))
             for g,c in person_totals.most_common(10)]
    top10_b = bar_chart(top10, color_map=EMPLOYER_COLORS)

    charts = f'''<div class="row">
        <div class="box"><h3>Activity Types</h3>{type_d}</div>
        <div class="box"><h3>By Project</h3>{proj_b}</div>
    </div>
    <div class="row">
        <div class="box"><h3>By Company</h3>{co_b}</div>
        <div class="box"><h3>Top 10 Contributors</h3>{top10_b}</div>
    </div>'''

    inact = inactive_callout(act, D["participants"])
    matrix = f'<div class="section"><h2>Project Breakdown</h2>{project_matrix(D["by_project"], proj_names)}</div>'

    body = cards + tl + charts + inact + matrix
    return page_wrap("NumFOCUS Series Dashboard", "Fall 2026 Cohort (Sep 14 – Nov 18)",
                     "index.html", body, proj_names, co_names, D["collected_at"])


def gen_project(D, proj_name):
    items = D["by_project"].get(proj_name,[])
    proj_names = list(D["projects"].keys())
    co_names = list(D["companies_config"].keys())
    slug = proj_name.lower().replace(" ","-")
    repo = D["projects"][proj_name]["repo"]

    n = len(items)
    prs = sum(1 for a in items if a["type"]=="pr")
    merged = sum(1 for a in items if a.get("merged"))
    commits = sum(1 for a in items if a["type"]=="commit")
    active = len(set(a.get("author","").lower() for a in items))

    cards = f'''<div class="cards">
        <div class="card"><div class="n">{n}</div><div class="l">Activities</div></div>
        <div class="card"><div class="n">{prs}</div><div class="l">PRs</div></div>
        <div class="card"><div class="n">{merged}</div><div class="l">Merged</div></div>
        <div class="card"><div class="n">{commits}</div><div class="l">Commits</div></div>
        <div class="card"><div class="n">{active}</div><div class="l">Active</div></div>
    </div>'''

    body = (f'<p style="color:var(--muted);text-align:center">Repo: <a href="https://github.com/{repo}">{repo}</a></p>'
            + cards
            + f'<div class="section"><h2>Timeline</h2>{timeline(items)}</div>'
            + f'<div class="section"><h2>Leaderboard</h2>{leaderboard(items, D["participants"])}</div>'
            + f'<div class="section"><h2>Activity Feed</h2>{activity_table(items)}</div>')

    return page_wrap(f"{proj_name} — NumFOCUS Series", f"Project activity for {proj_name}",
                     f"project-{slug}.html", body, proj_names, co_names, D["collected_at"])


def gen_company(D, co_name):
    items = D["by_company"].get(co_name,[])
    proj_names = list(D["projects"].keys())
    co_names = list(D["companies_config"].keys())
    slug = co_name.lower().replace(" ","-")

    n = len(items)
    prs = sum(1 for a in items if a["type"]=="pr")
    merged = sum(1 for a in items if a.get("merged"))
    commits = sum(1 for a in items if a["type"]=="commit")
    active = len(set(a.get("author","").lower() for a in items))

    # Project distribution for this company
    co_by_proj = Counter()
    for item in items: co_by_proj[item.get("repo","")] += 1
    r2p = {v["repo"]:k for k,v in D["projects"].items()}
    proj_dist = bar_chart([(r2p.get(r,r), c, None) for r,c in co_by_proj.most_common()])

    cards = f'''<div class="cards">
        <div class="card"><div class="n">{n}</div><div class="l">Activities</div></div>
        <div class="card"><div class="n">{prs}</div><div class="l">PRs</div></div>
        <div class="card"><div class="n">{merged}</div><div class="l">Merged</div></div>
        <div class="card"><div class="n">{commits}</div><div class="l">Commits</div></div>
        <div class="card"><div class="n">{active}</div><div class="l">Active</div></div>
    </div>'''

    body = (cards
            + f'<div class="row"><div class="box"><h3>Activity by Project</h3>{proj_dist}</div></div>'
            + f'<div class="section"><h2>Leaderboard</h2>{leaderboard(items, D["participants"])}</div>'
            + f'<div class="section"><h2>Activity Feed</h2>{activity_table(items)}</div>')

    return page_wrap(f"{co_name} — NumFOCUS Series", f"Activity from {co_name} participants",
                     f"company-{slug}.html", body, proj_names, co_names, D["collected_at"])


def gen_about(D):
    proj_names = list(D["projects"].keys())
    co_names = list(D["companies_config"].keys())

    proj_rows = ""
    for name, info in D["projects"].items():
        repo = info["repo"]
        proj_rows += f'<tr><td>{name}</td><td><a href="https://github.com/{repo}">{repo}</a></td></tr>'

    co_rows = "".join(f'<tr><td>{co}</td><td>{len(ids)}</td></tr>'
                      for co,ids in D["companies_config"].items())

    body = f'''
    <div class="section"><h2>What Is This?</h2>
    <p>This dashboard tracks upstream open source contributions by participants in the
    <strong>NumFOCUS Sustaining Open Source Series</strong> — a 10-week structured contribution
    program (Sep 14 – Nov 18, 2026) co-organized by Bloomberg, NVIDIA, AWS, and G-Research.</p></div>

    <div class="section"><h2>Tracked Projects</h2>
    <table class="t"><thead><tr><th>Project</th><th>Repository</th></tr></thead>
    <tbody>{proj_rows}</tbody></table></div>

    <div class="section"><h2>Companies</h2>
    <table class="t"><thead><tr><th>Company</th><th>Participants</th></tr></thead>
    <tbody>{co_rows}</tbody></table></div>

    <div class="section"><h2>Data Files</h2>
    <table class="t"><thead><tr><th>File</th><th>Description</th></tr></thead><tbody>
    <tr><td><a href="data.json">data.json</a></td><td>Complete activity dataset — every PR, issue, comment, commit, review</td></tr>
    <tr><td><a href="summary.json">summary.json</a></td><td>Aggregated stats — totals, by-project, by-company, leaderboard</td></tr>
    <tr><td><a href="participants.json">participants.json</a></td><td>Participant roster — GitHub IDs by company</td></tr>
    </tbody></table></div>

    <div class="section"><h2>data.json schema</h2>
    <pre class="json">{{
  "collected_at": "ISO-8601",
  "activity": [
    {{ "type": "pr|issue|comment|review|commit", "repo": "owner/repo",
       "author": "github_login", "person_name": "Name", "company": "AWS|Bloomberg",
       "created_at": "ISO-8601", "url": "https://github.com/...",
       "merged": true|false, "state": "open|closed" }}
  ],
  "summary": {{ "total_activities": N, "prs": N, "commits": N, "issues": N, "comments": N, "reviews": N }}
}}</pre></div>

    <div class="section"><h2>Collection</h2>
    <p>Data collected via GitHub REST API. Tracks PRs, commits, issues, comments, and reviews
    by cohort participants since Sep 14. Cached with ETags for efficient re-runs.</p></div>'''

    return page_wrap("NumFOCUS Series — Data API", "Open data for the Fall 2026 cohort",
                     "about.html", body, proj_names, co_names, D["collected_at"])


def gen_summary_json(D):
    act = D["activity"]; participants = D["participants"]
    r2p = {v["repo"]:k for k,v in D["projects"].items()}
    bp = Counter(); bc = Counter()
    ps = defaultdict(lambda:{"prs":0,"merged":0,"commits":0,"issues":0,"comments":0,"reviews":0,"total":0})
    for item in act:
        bp[r2p.get(item.get("repo",""),"?")]+=1
        bc[item.get("company","?")]+=1
        a=item.get("author","").lower(); t=item["type"]
        ps[a]["total"]+=1
        if t=="pr": ps[a]["prs"]+=1; ps[a]["merged"]+=int(bool(item.get("merged")))
        elif t=="commit": ps[a]["commits"]+=1
        elif t=="issue": ps[a]["issues"]+=1
        elif t=="comment": ps[a]["comments"]+=1
        elif t=="review": ps[a]["reviews"]+=1
    lb = sorted([{"github":g,"name":participants.get(g,{}).get("name",g),
                  "company":participants.get(g,{}).get("company","?"),**s}
                 for g,s in ps.items()], key=lambda x:x["total"], reverse=True)[:25]
    return {"collected_at":D["collected_at"],
            "totals":{"activities":len(act),"prs":D["summary"]["prs"],
                      "merged":sum(1 for a in act if a.get("merged")),
                      "commits":D["summary"].get("commits",0),
                      "issues":D["summary"]["issues"],"comments":D["summary"]["comments"],
                      "reviews":D["summary"]["reviews"],
                      "active_people":len(set(a.get("author","").lower() for a in act))},
            "by_project":dict(bp.most_common()),
            "by_company":dict(bc.most_common()),
            "leaderboard":lb}


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    if not DATA_FILE.exists():
        print(f"❌ {DATA_FILE} not found — run collect.py first"); sys.exit(1)

    D = load_data()
    OUTPUT_DIR.mkdir(exist_ok=True)

    (OUTPUT_DIR/"index.html").write_text(gen_index(D))
    print("✅ index.html")

    for pname in D["projects"]:
        slug = pname.lower().replace(" ","-")
        (OUTPUT_DIR/f"project-{slug}.html").write_text(gen_project(D, pname))
        print(f"✅ project-{slug}.html")

    for cname in D["companies_config"]:
        slug = cname.lower().replace(" ","-")
        (OUTPUT_DIR/f"company-{slug}.html").write_text(gen_company(D, cname))
        print(f"✅ company-{slug}.html")

    (OUTPUT_DIR/"about.html").write_text(gen_about(D))
    print("✅ about.html")

    shutil.copy(DATA_FILE, OUTPUT_DIR/"data.json")
    shutil.copy(BASE_DIR/"participants.json", OUTPUT_DIR/"participants.json")
    (OUTPUT_DIR/"summary.json").write_text(json.dumps(gen_summary_json(D), indent=2))
    print("✅ data.json, summary.json, participants.json")

    t = D["summary"]["total_activities"]
    print(f"\n📊 {t} activities, {len(D['participants'])} people, {len(D['projects'])} projects")


if __name__ == "__main__":
    main()
