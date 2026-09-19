#!/bin/zsh
# Collect data from GitHub and generate dashboard
# Requires: GITHUB_TOKEN env var
cd "$(dirname "$0")"

# Ensure GITHUB_TOKEN is set
if [[ -z "$GITHUB_TOKEN" ]]; then
    # Try sourcing zshrc for the token
    [[ -f ~/.zshrc ]] && source ~/.zshrc 2>/dev/null
fi

if [[ -z "$GITHUB_TOKEN" ]]; then
    echo "❌ GITHUB_TOKEN not set. Export it or add to ~/.zshrc"
    exit 1
fi

echo "=== Collecting GitHub data ==="
uv run --no-project python collect.py
if [[ $? -ne 0 ]]; then
    echo "❌ Collection failed"
    exit 1
fi

echo ""
echo "=== Generating dashboard ==="
uv run --no-project python generate_dashboard.py
if [[ $? -ne 0 ]]; then
    echo "❌ Dashboard generation failed"
    exit 1
fi

echo ""
echo "✅ Dashboard ready at: dashboard/index.html"
echo "   Open with: open dashboard/index.html"
