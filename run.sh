#!/bin/sh
# Collect data from GitHub and generate dashboard
# Requires: GITHUB_TOKEN env var (or a .env file in the same directory)
cd "$(dirname "$0")"

# Ensure GITHUB_TOKEN is set
if [[ -z "$GITHUB_TOKEN" ]]; then
    # Try sourcing bashrc for the token
    [[ -f ~/.bashrc ]] && source ~/.bashrc 2>/dev/null
fi

if [[ -z "$GITHUB_TOKEN" ]]; then
    echo "❌ GITHUB_TOKEN not set. Export it or add to ~/.bashrc"
    exit 1
fi

echo "=== Collecting GitHub data ==="
if [[ "$*" == *"--graphql"* ]]; then
    echo "Using GraphQL collector"
    uv run python collect_graphql.py "$@"
else
    uv run python collect.py "$@"
fi
if [[ $? -ne 0 ]]; then
    echo "❌ Collection failed"
    exit 1
fi

echo ""
echo "=== Generating dashboard ==="
uv run python generate_dashboard.py
if [[ $? -ne 0 ]]; then
    echo "❌ Dashboard generation failed"
    exit 1
fi

echo ""
echo "✅ Dashboard ready at: dashboard/index.html"
echo "   Open with: open dashboard/index.html"
