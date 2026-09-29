#!/bin/sh
# Collect data from GitHub and generate the NumFOCUS Series dashboard.
# Requires: GITHUB_TOKEN env var (or a .env / ~/.bashrc that exports it)
cd "$(dirname "$0")"

usage() {
    cat <<'EOF'
Usage: ./run.sh [OPTIONS]

Collects GitHub activity for the tracked NumFOCUS Series participants and
regenerates the static dashboard in ./dashboard/.

Options:
  --graphql       Use the GraphQL collector (collect_graphql.py) instead of
                  the default REST collector (collect.py). The GraphQL path
                  makes far fewer API calls and is much faster for the large
                  repos (pandas, NumPy, SciPy) — recommended once you have a
                  token with GraphQL access.
  --no-cache      Force a fresh fetch, ignoring the HTTP response cache in
                  ./.cache/. Use when you suspect stale data. Normal runs
                  reuse the cache (ETags / If-Modified-Since → 304 = free),
                  so most re-runs finish in well under a minute.
  -h, --help      Show this help and exit (no collection or generation runs).

Environment:
  GITHUB_TOKEN    Required. A GitHub personal access token (public-repo scope
                  is enough — all tracked data is public). If unset, run.sh
                  tries to source ~/.bashrc. Create one at
                  https://github.com/settings/tokens and export it:
                      export GITHUB_TOKEN=ghp_xx…

Output (in ./dashboard/):
  index.html            Overview: charts, timeline, project breakdown matrix
  project-<name>.html   Per-project page (multi-repo projects include a
                        per-repo breakdown table)
  company-<name>.html   Per-company page
  about.html            Data API documentation
  data.json             Complete raw activity dataset
  summary.json          Aggregated stats
  participants.json     Roster (copy of your config)

Examples:
  ./run.sh                      # REST collector, using cache
  ./run.sh --graphql            # faster GraphQL collector
  ./run.sh --graphql --no-cache # GraphQL, force a full fresh fetch

Publish by copying ./dashboard/ to any static host, e.g.:
  rsync -av dashboard/ yourserver:/var/www/numfocus/
EOF
}

# Show help without requiring a token or running anything.
case " $* " in
    *" -h "*|*" --help "*)
        usage
        exit 0
        ;;
esac

# Ensure GITHUB_TOKEN is set
if [ -z "$GITHUB_TOKEN" ]; then
    # Try sourcing bashrc for the token
    [ -f ~/.bashrc ] && . ~/.bashrc 2>/dev/null
fi

if [ -z "$GITHUB_TOKEN" ]; then
    echo "❌ GITHUB_TOKEN not set. Export it or add to ~/.bashrc"
    echo "   Run './run.sh --help' for details."
    exit 1
fi

echo "=== Collecting GitHub data ==="
if [ "${*#*--graphql}" != "$*" ]; then
    echo "Using GraphQL collector"
    uv run python collect_graphql.py "$@"
else
    uv run python collect.py "$@"
fi
if [ $? -ne 0 ]; then
    echo "❌ Collection failed"
    exit 1
fi

echo ""
echo "=== Generating dashboard ==="
uv run python generate_dashboard.py
if [ $? -ne 0 ]; then
    echo "❌ Dashboard generation failed"
    exit 1
fi

echo ""
echo "✅ Dashboard ready at: dashboard/index.html"
echo "   Open with: open dashboard/index.html"
