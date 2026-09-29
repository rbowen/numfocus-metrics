#!/usr/bin/env python3
"""
NumFOCUS Series — GitHub activity collector (GraphQL v4) with caching.

Queries the GitHub GraphQL API for PRs, commits, issues, comments, and reviews
by tracked participants across all NumFOCUS project repos.

Caching strategy:
  - Per-request file cache keyed by hash(query + variables)
  - Stored in .cache/ directory as JSON files
  - On repeat runs, cached pages are returned instantly (no API calls)
  - Cache is invalidated per-page, so new activity is always picked up

Usage:
    GITHUB_TOKEN=ghp_... uv run python collect_graphql.py
    GITHUB_TOKEN=ghp_... uv run python collect_graphql.py --no-cache  # force fresh

Output: data.json (consumed by generate_dashboard.py)
"""

import hashlib, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
import requests

# Load .env file directly so the token is available regardless of how uv
# passes (or strips) environment variables to the subprocess.
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _, _v = _line.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GRAPHQL_URL  = "https://api.github.com/graphql"
SERIES_START = "2026-08-15T00:00:00Z"

BASE_DIR          = Path(__file__).parent
PARTICIPANTS_FILE  = BASE_DIR / "participants.json"
DATA_FILE         = BASE_DIR / "data_graphql.json"
CACHE_DIR         = BASE_DIR / ".cache"

USE_CACHE = "--no-cache" not in sys.argv


# ─── Cache layer ─────────────────────────────────────────────────────────────

def cache_key(query: str, variables: dict) -> str:
    blob = query + json.dumps(variables, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def load_cache(key: str):
    path = CACHE_DIR / f"{key}.json"
    if path.exists() and USE_CACHE:
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return None


def save_cache(key: str, data):
    CACHE_DIR.mkdir(exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(json.dumps({
        "data": data,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }))


# ─── GraphQL client ───────────────────────────────────────────────────────────

session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Content-Type": "application/json",
})


def gql(query: str, variables: dict) -> dict:
    key    = cache_key(query, variables)
    cached = load_cache(key)
    if cached:
        return cached["data"]

    time.sleep(2)  # avoid GitHub secondary rate limit

    for attempt in range(6):
        resp = session.post(GRAPHQL_URL, json={"query": query, "variables": variables})

        if resp.status_code in (403, 429):
            reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait  = max(reset - int(time.time()), 0) + 5
            print(f"  ⏳ Rate limit hit, waiting {wait}s...")
            time.sleep(wait)
            continue

        resp.raise_for_status()
        payload = resp.json()

        if "errors" in payload:
            msgs = [e.get("message", "") for e in payload["errors"]]
            if any("rate limit" in m.lower() for m in msgs):
                wait = 30 * (attempt + 1)
                print(f"  ⏳ Secondary rate limit, waiting {wait}s...")
                time.sleep(wait)
                continue
            for m in msgs:
                print(f"  ⚠️  GraphQL error: {m}")
            if "data" not in payload:
                return {}

        data = payload.get("data", {})
        save_cache(key, data)
        return data

    print("  ❌ Failed after 6 attempts")
    return {}


# ─── GraphQL queries ──────────────────────────────────────────────────────────

REPO_PRS_QUERY = """
query($owner: String!, $repo: String!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequests(first: 50, after: $cursor, states: [OPEN, CLOSED, MERGED],
                 orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        title url createdAt updatedAt state mergedAt
        author { login }
        reviews(first: 50) {
          nodes { author { login } state url createdAt }
        }
        comments(first: 100) {
          nodes { author { login } body url createdAt }
        }
        reviewThreads(first: 50) {
          nodes {
            comments(first: 50) {
              nodes { author { login } body url createdAt }
            }
          }
        }
      }
    }
  }
}
"""

REPO_ISSUES_QUERY = """
query($owner: String!, $repo: String!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    issues(first: 50, after: $cursor, states: [OPEN, CLOSED],
           orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        title url createdAt updatedAt
        author { login }
        comments(first: 100) {
          nodes { author { login } body url createdAt }
        }
      }
    }
  }
}
"""

COMMITS_QUERY = """
query($owner: String!, $repo: String!, $since: GitTimestamp!, $until: GitTimestamp!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $cursor, since: $since, until: $until) {
            pageInfo { hasNextPage endCursor }
            nodes {
              messageHeadline url committedDate
              author { user { login } }
            }
          }
        }
      }
    }
  }
}
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def in_window(ts: str) -> bool:
    if not ts:
        return False
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt >= datetime.fromisoformat(SERIES_START.replace("Z", "+00:00"))


def make_record(kind, author, repo, title, url, ts, extra=None):
    rec = {
        "type":       kind,
        "repo":       repo,
        "author":     author,
        "title":      str(title).replace("\n", " ")[:120],
        "url":        url,
        "created_at": ts,
    }
    if extra:
        rec.update(extra)
    return rec


# ─── Collectors ───────────────────────────────────────────────────────────────

def collect_prs_reviews_comments(repo: str, all_ids: set) -> list:
    owner, name = repo.split("/")
    records = []
    cursor  = None
    pages   = 0

    print(f"  PRs + reviews + comments for {repo}...")
    while pages < 50:
        data = gql(REPO_PRS_QUERY, {"owner": owner, "repo": name, "cursor": cursor})
        prs  = (data.get("repository") or {}).get("pullRequests", {})

        stop = False
        for pr in prs.get("nodes", []):
            updated = pr.get("updatedAt", "")
            if updated and not in_window(updated):
                stop = True
                break

            pr_title   = pr.get("title", "")
            pr_url     = pr.get("url", "")
            pr_created = pr.get("createdAt", "")
            pr_author  = (pr.get("author") or {}).get("login", "").lower()
            merged     = pr.get("mergedAt") is not None
            state      = pr.get("state", "OPEN").lower()
            if state == "merged":
                state = "closed"

            if pr_author in all_ids and in_window(pr_created):
                records.append(make_record(
                    "pr", pr_author, repo, pr_title, pr_url, pr_created,
                    {"state": state, "merged": merged},
                ))

            for review in pr.get("reviews", {}).get("nodes", []):
                login = (review.get("author") or {}).get("login", "").lower()
                if login not in all_ids or login == pr_author:
                    continue
                ts = review.get("createdAt", "")
                if not in_window(ts):
                    continue
                records.append(make_record(
                    "review", login, repo,
                    f"{review.get('state','').title()}: {pr_title}",
                    review.get("url", ""), ts,
                ))

            for comment in pr.get("comments", {}).get("nodes", []):
                login = (comment.get("author") or {}).get("login", "").lower()
                if login not in all_ids:
                    continue
                ts = comment.get("createdAt", "")
                if not in_window(ts):
                    continue
                records.append(make_record(
                    "comment", login, repo,
                    comment.get("body", ""), comment.get("url", ""), ts,
                ))

            for thread in pr.get("reviewThreads", {}).get("nodes", []):
                for comment in thread.get("comments", {}).get("nodes", []):
                    login = (comment.get("author") or {}).get("login", "").lower()
                    if login not in all_ids:
                        continue
                    ts = comment.get("createdAt", "")
                    if not in_window(ts):
                        continue
                    records.append(make_record(
                        "comment", login, repo,
                        comment.get("body", ""), comment.get("url", ""), ts,
                    ))

        page_info = prs.get("pageInfo", {})
        if stop or not page_info.get("hasNextPage"):
            break
        cursor = page_info["endCursor"]
        pages += 1

    print(f"    → {len(records)} PR/review/comment events")
    return records


def collect_issues(repo: str, all_ids: set) -> list:
    owner, name = repo.split("/")
    records = []
    cursor  = None
    pages   = 0

    print(f"  Issues + issue comments for {repo}...")
    while pages < 50:
        data   = gql(REPO_ISSUES_QUERY, {"owner": owner, "repo": name, "cursor": cursor})
        issues = (data.get("repository") or {}).get("issues", {})

        stop = False
        for issue in issues.get("nodes", []):
            updated = issue.get("updatedAt", "")
            if updated and not in_window(updated):
                stop = True
                break

            issue_title   = issue.get("title", "")
            issue_url     = issue.get("url", "")
            issue_created = issue.get("createdAt", "")
            issue_author  = (issue.get("author") or {}).get("login", "").lower()

            if issue_author in all_ids and in_window(issue_created):
                records.append(make_record(
                    "issue", issue_author, repo, issue_title, issue_url, issue_created,
                ))

            for comment in issue.get("comments", {}).get("nodes", []):
                login = (comment.get("author") or {}).get("login", "").lower()
                if login not in all_ids:
                    continue
                ts = comment.get("createdAt", "")
                if not in_window(ts):
                    continue
                records.append(make_record(
                    "comment", login, repo,
                    comment.get("body", ""), comment.get("url", ""), ts,
                ))

        page_info = issues.get("pageInfo", {})
        if stop or not page_info.get("hasNextPage"):
            break
        cursor = page_info["endCursor"]
        pages += 1

    print(f"    → {len(records)} issue/comment events")
    return records


def collect_commits(repo: str, all_ids: set) -> list:
    owner, name = repo.split("/")
    records = []
    cursor  = None

    print(f"  Commits for {repo}...")
    until = datetime.now(timezone.utc).isoformat()
    while True:
        data    = gql(COMMITS_QUERY, {
            "owner": owner, "repo": name,
            "since": SERIES_START, "until": until,
            "cursor": cursor,
        })
        history = (
            (data.get("repository") or {})
            .get("defaultBranchRef") or {}
        ).get("target", {}).get("history", {})

        for node in history.get("nodes", []):
            login = ((node.get("author") or {}).get("user") or {}).get("login", "").lower()
            if login not in all_ids:
                continue
            records.append(make_record(
                "commit", login, repo,
                node.get("messageHeadline", ""),
                node.get("url", ""),
                node.get("committedDate", ""),
            ))

        page_info = history.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info["endCursor"]

    print(f"    → {len(records)} commits")
    return records


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not GITHUB_TOKEN:
        print("❌ Set GITHUB_TOKEN environment variable")
        sys.exit(1)

    start_time = time.time()

    config    = json.loads(PARTICIPANTS_FILE.read_text())
    projects  = config["projects"]
    companies = config["companies"]

    all_ids      = set()
    id_to_person = {}
    for company, people in companies.items():
        for p in people:
            gh = p.get("github", "").strip()
            if gh:
                all_ids.add(gh.lower())
                id_to_person[gh.lower()] = {
                    "name": p["name"], "company": company, "github": gh,
                }

    per_company     = {co: len([p for p in ppl if p.get("github")]) for co, ppl in companies.items()}
    company_summary = ", ".join(f"{co}: {n}" for co, n in per_company.items())
    cache_status    = "enabled" if USE_CACHE else "DISABLED (--no-cache)"

    print(f"Tracking {len(all_ids)} participants across {len(projects)} projects ({company_summary})")
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
        all_activity.extend(collect_prs_reviews_comments(repo, all_ids))
        all_activity.extend(collect_issues(repo, all_ids))
        all_activity.extend(collect_commits(repo, all_ids))

    for item in all_activity:
        author_lower = item.get("author", "").lower()
        person = id_to_person.get(author_lower, {})
        item["person_name"] = person.get("name", item.get("author", ""))
        item["company"]     = person.get("company", "Unknown")

    output = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "series_start": SERIES_START,
        "projects":     projects,
        "companies":    {co: [p["github"] for p in people if p.get("github")]
                         for co, people in companies.items()},
        "participants": id_to_person,
        "activity": sorted(
            all_activity,
            key=lambda x: x.get("created_at", x.get("submitted_at", "")),
            reverse=True,
        ),
        "summary": {
            "total_activities": len(all_activity),
            "prs":      sum(1 for a in all_activity if a["type"] == "pr"),
            "commits":  sum(1 for a in all_activity if a["type"] == "commit"),
            "issues":   sum(1 for a in all_activity if a["type"] == "issue"),
            "comments": sum(1 for a in all_activity if a["type"] == "comment"),
            "reviews":  sum(1 for a in all_activity if a["type"] == "review"),
        },
    }

    DATA_FILE.write_text(json.dumps(output, indent=2))

    elapsed    = time.time() - start_time
    mins, secs = divmod(int(elapsed), 60)
    duration   = f"{mins}m {secs}s" if mins else f"{secs}s"

    print(f"\n✅ Wrote {DATA_FILE} — {len(all_activity)} activities in {duration}")
    print(f"   PRs: {output['summary']['prs']}, Commits: {output['summary']['commits']}, "
          f"Issues: {output['summary']['issues']}, Comments: {output['summary']['comments']}, "
          f"Reviews: {output['summary']['reviews']}")


if __name__ == "__main__":
    main()
