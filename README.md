# NumFOCUS Series Dashboard

Track upstream open source contributions by participants in the
[NumFOCUS Sustaining Open Source Series](https://numfocus.org/programs/sustainability-series).

Produces a static HTML dashboard showing PRs, commits, issues, comments,
and code reviews across five scientific Python projects — broken down by
project and by company.

## Quick Start

```bash
# 1. Clone
git clone https://github.com/rbowen/numfocus-dashboard.git
cd numfocus-dashboard

# 2. Create your participant roster (see participants.json.example)
cp participants.json.example participants.json
# Edit participants.json with your GitHub handles

# 3. Set your GitHub token
export GITHUB_TOKEN=ghp_...

# 4. Run
./run.sh

# 5. Open the dashboard
open dashboard/index.html
```

Requires Python 3.11+ and [uv](https://github.com/astral-sh/uv). The
script installs its only dependency (`requests`) automatically via uv.

## What It Does

**`collect.py`** queries the GitHub API for activity by tracked
participants across all configured project repos since a configurable
start date. It collects:

- Pull requests (open, merged, closed)
- Git commits
- Issues opened
- Issue and PR comments
- PR reviews

Results are cached locally (`.cache/`) using HTTP ETags and
`If-Modified-Since` headers. First runs take 15–45 minutes depending
on repo size; subsequent runs are typically under a minute because
unchanged responses return 304 and cost zero API quota.

**`generate_dashboard.py`** reads the collected data and produces a
self-contained static site in `dashboard/`:

- **Overview** — summary cards, daily activity timeline, charts by
  project/company/type, top contributors, inactive participant callout,
  project breakdown matrix
- **Per-project pages** — timeline, leaderboard, and activity feed for
  each tracked project
- **Per-company pages** — project distribution, leaderboard, and feed
  for each participating company
- **Data API page** — schema docs and download links for the raw JSON

The `dashboard/` directory is fully standalone (HTML + CSS, no build
step) and can be published to any static hosting.

## Configuration

All configuration lives in `participants.json`:

```json
{
  "projects": {
    "ProjectName": { "repo": "owner/repo" }
  },
  "companies": {
    "CompanyName": [
      { "name": "Full Name", "github": "github_username" }
    ]
  }
}
```

See `participants.json.example` for the full structure.

To change the series start date, edit `SERIES_START` in `collect.py`.

## Output

After running, `dashboard/` contains:

| File | Description |
|------|-------------|
| `index.html` | Overview dashboard with charts |
| `project-{name}.html` | Per-project detail page |
| `company-{name}.html` | Per-company detail page |
| `about.html` | Data API documentation |
| `data.json` | Complete raw activity dataset |
| `summary.json` | Aggregated stats for embedding |
| `participants.json` | Roster (copy of your config) |

All JSON files are published alongside the HTML for programmatic
consumers — build your own views, Slack bots, or Grafana panels on
top of them.

## Caching

The collector uses HTTP conditional requests (ETags /
`If-Modified-Since`) to avoid re-fetching unchanged data. Cache files
are stored in `.cache/` and keyed by URL hash.

- **First run**: fills the cache (~600–800 API calls). Takes 15–45 min.
- **Subsequent runs**: mostly 304 Not Modified. Under a minute.
- **Force fresh**: `uv run --no-project python collect.py --no-cache`

GitHub rate limit is 5,000 requests/hour for authenticated tokens. The
collector reads `X-RateLimit-Remaining` from response headers and
sleeps automatically if the budget gets low.

## Running on a Schedule

Set up a cron job to collect nightly and publish:

```bash
# Collect at 3 AM, then rsync to your web server
0 3 * * * cd /path/to/numfocus-dashboard && GITHUB_TOKEN=ghp_... ./run.sh && rsync -av dashboard/ yourserver:/var/www/numfocus/
```

## Background

The NumFOCUS Sustaining Open Source Series is a structured 10-week
contribution program co-organized by Bloomberg, NVIDIA, AWS, and
G-Research in partnership with [NumFOCUS](https://numfocus.org).
Engineers from participating companies contribute upstream to
scientific Python projects under maintainer mentorship.

This dashboard was built to give program organizers and participants
visibility into cohort activity across all five target projects.

## License

Licensed under the Apache License 2.0. See [LICENSE](LICENSE).
