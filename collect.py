#!/usr/bin/env python3
"""
NumFOCUS Series — GitHub activity collector with caching.

Queries the GitHub API for PRs, commits, issues, issue comments, and PR reviews
by tracked participants across all NumFOCUS project repos.

Caching strategy:
  - Per-endpoint HTTP cache using ETags and Last-Modified headers
  - Stored in .cache/ directory as JSON files keyed by URL hash
  - On repeat runs, sends If-None-Match / If-Modified-Since → 304 = free
  - PRs/issues list endpoints: cache the full listing, only re-fetch if changed
  - Commits per-user: cached per (repo, user) pair

Usage:
    GITHUB_TOKEN=ghp_... uv run python collect.py
    GITHUB_TOKEN=ghp_... uv run python collect.py --no-cache  # force fresh

Output: data.json (consumed by generate_dashboard.py)
"""

import hashlib, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
import requests

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}
API = "https://api.github.com"
SERIES_START = "2026-09-14T00:00:00Z"

BASE_DIR = Path(__file__).parent
PARTICIPANTS_FILE = BASE_DIR / "participants.json"
DATA_FILE = BASE_DIR / "data.json"
CACHE_DIR = BASE_DIR / ".cache"

USE_CACHE = "--no-cache" not in sys.argv


# ─── HTTP Cache Layer ────────────────────────────────────────────────────────

def cache_key(url, params=None):
    """Stable hash for a URL + params combo."""
    blob = url + json.dumps(params or {}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def load_cache(key):
    """Load cached response data + headers."""
    path = CACHE_DIR / f"{key}.json"
    if path.exists() and USE_CACHE:
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return None


def save_cache(key, data, etag=None, last_modified=None):
    """Save response data + conditional headers."""
    CACHE_DIR.mkdir(exist_ok=True)
    payload = {
        "data": data,
        "etag": etag,
        "last_modified": last_modified,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    (CACHE_DIR / f"{key}.json").write_text(json.dumps(payload))


# ─── API Layer ───────────────────────────────────────────────────────────────

def api_get(url, params=None):
    """GET with rate-limit awareness + conditional request caching."""
    key = cache_key(url, params)
    cached = load_cache(key)

    req_headers = dict(HEADERS)
    if cached:
        if cached.get("etag"):
            req_headers["If-None-Match"] = cached["etag"]
        if cached.get("last_modified"):
            req_headers["If-Modified-Since"] = cached["last_modified"]

    resp = requests.get(url, headers=req_headers, params=params, timeout=30)

    # Rate limit handling (read from response headers, not /rate_limit endpoint)
    remaining = int(resp.headers.get("X-RateLimit-Remaining", 999))
    if remaining < 50:
        reset = int(resp.headers.get("X-RateLimit-Reset", 0))
        wait = max(reset - int(time.time()), 1)
        print(f"  ⏳ Rate limit low ({remaining}), sleeping {wait}s")
        time.sleep(wait)
    if resp.status_code == 403 and "rate limit" in resp.text.lower():
        reset = int(resp.headers.get("X-RateLimit-Reset", 0))
        wait = max(reset - int(time.time()), 5)
        print(f"  🛑 Rate limited, sleeping {wait}s")
        time.sleep(wait)
        return api_get(url, params)

    if resp.status_code == 304 and cached:
        # Not modified — return cached data, no API quota consumed
        return CachedResponse(cached["data"], 200, resp.headers)

    if resp.status_code == 200:
        data = resp.json()
        save_cache(key, data,
                   etag=resp.headers.get("ETag"),
                   last_modified=resp.headers.get("Last-Modified"))

    return resp


class CachedResponse:
    """Mimics requests.Response for cached 304 results."""
    def __init__(self, data, status_code, headers):
        self._data = data
        self.status_code = status_code
        self.headers = headers
        self.text = json.dumps(data)
    def json(self):
        return self._data


def paginate(url, params=None):
    """Paginate through all results with caching."""
    params = params or {}
    params.setdefault("per_page", 100)
    results = []
    page_num = 0
    while url:
        page_num += 1
        resp = api_get(url, params)
        if resp.status_code != 200:
            print(f"  ⚠️  {resp.status_code} for {url}")
            break
        data = resp.json()
        if not data:
            break
        results.extend(data)
        # Follow Link: <next> header
        link = resp.headers.get("Link", "")
        url = None
        params = None
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.split("<")[1].split(">")[0]
    return results


# ─── Collectors ──────────────────────────────────────────────────────────────

def collect_prs(repo, github_ids):
    """Collect PRs authored by any participant in a repo."""
    print(f"  PRs for {repo}...")
    prs = []
    for pr in paginate(f"{API}/repos/{repo}/pulls",
                       {"state": "all", "sort": "created", "direction": "desc",
                        "since": SERIES_START}):
        created = pr.get("created_at", "")
        if created < SERIES_START:
            break
        author = (pr.get("user") or {}).get("login", "").lower()
        if author in github_ids:
            prs.append({
                "type": "pr",
                "repo": repo,
                "number": pr["number"],
                "title": pr["title"],
                "author": (pr.get("user") or {}).get("login", ""),
                "state": pr["state"],
                "merged": pr.get("merged_at") is not None,
                "created_at": created,
                "updated_at": pr.get("updated_at", ""),
                "url": pr["html_url"],
            })
    print(f"    → {len(prs)} PRs")
    return prs


def collect_issues(repo, github_ids):
    """Collect issues opened by participants."""
    print(f"  Issues for {repo}...")
    issues = []
    for iss in paginate(f"{API}/repos/{repo}/issues",
                        {"state": "all", "sort": "created", "direction": "desc",
                         "since": SERIES_START}):
        if iss.get("pull_request"):
            continue
        created = iss.get("created_at", "")
        if created < SERIES_START:
            break
        author = (iss.get("user") or {}).get("login", "").lower()
        if author in github_ids:
            issues.append({
                "type": "issue",
                "repo": repo,
                "number": iss["number"],
                "title": iss["title"],
                "author": (iss.get("user") or {}).get("login", ""),
                "state": iss["state"],
                "created_at": created,
                "url": iss["html_url"],
            })
    print(f"    → {len(issues)} issues")
    return issues


def collect_commits(repo, github_ids):
    """Collect commits authored by participants (cached per user)."""
    print(f"  Commits for {repo}...")
    commits = []
    seen_shas = set()
    for gh_id in github_ids:
        for c in paginate(f"{API}/repos/{repo}/commits",
                          {"author": gh_id, "since": SERIES_START}):
            sha = c.get("sha", "")
            if sha in seen_shas:
                continue
            seen_shas.add(sha)
            commit_data = c.get("commit", {})
            author_info = c.get("author") or {}
            created = commit_data.get("author", {}).get("date", "")
            if created < SERIES_START:
                continue
            commits.append({
                "type": "commit",
                "repo": repo,
                "sha": sha[:8],
                "title": commit_data.get("message", "").split("\n")[0][:120],
                "author": author_info.get("login", gh_id),
                "created_at": created,
                "url": c.get("html_url", ""),
            })
    print(f"    → {len(commits)} commits")
    return commits


def collect_issue_comments(repo, github_ids):
    """Collect issue/PR comments by participants."""
    print(f"  Comments for {repo}...")
    comments = []
    for c in paginate(f"{API}/repos/{repo}/issues/comments",
                      {"sort": "created", "direction": "desc",
                       "since": SERIES_START}):
        created = c.get("created_at", "")
        if created < SERIES_START:
            break
        author = (c.get("user") or {}).get("login", "").lower()
        if author in github_ids:
            comments.append({
                "type": "comment",
                "repo": repo,
                "author": (c.get("user") or {}).get("login", ""),
                "created_at": created,
                "issue_url": c.get("html_url", ""),
                "body_preview": (c.get("body") or "")[:200],
            })
    print(f"    → {len(comments)} comments")
    return comments


def collect_pr_reviews(repo, github_ids):
    """Collect PR reviews by participants (checks recent PRs)."""
    print(f"  PR reviews for {repo}...")
    reviews = []
    recent_prs = paginate(f"{API}/repos/{repo}/pulls",
                          {"state": "all", "sort": "updated", "direction": "desc",
                           "per_page": 50})
    for pr in recent_prs[:50]:
        if (pr.get("updated_at", "") or "") < SERIES_START:
            continue
        pr_reviews = api_get(f"{API}/repos/{repo}/pulls/{pr['number']}/reviews").json()
        if not isinstance(pr_reviews, list):
            continue
        for r in pr_reviews:
            submitted = r.get("submitted_at", "")
            if submitted < SERIES_START:
                continue
            author = (r.get("user") or {}).get("login", "").lower()
            if author in github_ids:
                reviews.append({
                    "type": "review",
                    "repo": repo,
                    "pr_number": pr["number"],
                    "pr_title": pr["title"],
                    "author": (r.get("user") or {}).get("login", ""),
                    "state": r.get("state", ""),
                    "submitted_at": submitted,
                    "url": r.get("html_url", ""),
                })
    print(f"    → {len(reviews)} reviews")
    return reviews


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    if not GITHUB_TOKEN:
        print("❌ Set GITHUB_TOKEN environment variable")
        sys.exit(1)

    config = json.loads(PARTICIPANTS_FILE.read_text())
    projects = config["projects"]
    companies = config["companies"]

    all_ids = set()
    id_to_person = {}
    for company, people in companies.items():
        for p in people:
            gh = p.get("github", "").strip()
            if gh:
                all_ids.add(gh.lower())
                id_to_person[gh.lower()] = {"name": p["name"], "company": company, "github": gh}

    cache_status = "enabled" if USE_CACHE else "DISABLED (--no-cache)"
    print(f"Tracking {len(all_ids)} participants across {len(projects)} projects")
    print(f"Series start: {SERIES_START}")
    print(f"Cache: {cache_status}")
    if CACHE_DIR.exists() and USE_CACHE:
        n_cached = len(list(CACHE_DIR.glob("*.json")))
        print(f"Cache dir: {CACHE_DIR} ({n_cached} cached responses)")
    print()

    all_activity = []
    for proj_name, proj_info in projects.items():
        repo = proj_info["repo"]
        print(f"\n📦 {proj_name} ({repo})")
        all_activity.extend(collect_prs(repo, all_ids))
        all_activity.extend(collect_commits(repo, all_ids))
        all_activity.extend(collect_issues(repo, all_ids))
        all_activity.extend(collect_issue_comments(repo, all_ids))
        all_activity.extend(collect_pr_reviews(repo, all_ids))

    for item in all_activity:
        author_lower = item.get("author", "").lower()
        person = id_to_person.get(author_lower, {})
        item["person_name"] = person.get("name", item.get("author", ""))
        item["company"] = person.get("company", "Unknown")

    output = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "series_start": SERIES_START,
        "projects": projects,
        "companies": {co: [p["github"] for p in people if p.get("github")]
                      for co, people in companies.items()},
        "participants": id_to_person,
        "activity": sorted(all_activity,
                           key=lambda x: x.get("created_at", x.get("submitted_at", "")),
                           reverse=True),
        "summary": {
            "total_activities": len(all_activity),
            "prs": sum(1 for a in all_activity if a["type"] == "pr"),
            "commits": sum(1 for a in all_activity if a["type"] == "commit"),
            "issues": sum(1 for a in all_activity if a["type"] == "issue"),
            "comments": sum(1 for a in all_activity if a["type"] == "comment"),
            "reviews": sum(1 for a in all_activity if a["type"] == "review"),
        }
    }

    DATA_FILE.write_text(json.dumps(output, indent=2))
    print(f"\n✅ Wrote {DATA_FILE} — {len(all_activity)} activities")
    print(f"   PRs: {output['summary']['prs']}, Commits: {output['summary']['commits']}, "
          f"Issues: {output['summary']['issues']}, Comments: {output['summary']['comments']}, "
          f"Reviews: {output['summary']['reviews']}")


if __name__ == "__main__":
    main()
