#!/usr/bin/env bash
# Make the repo public and turn on GitHub Pages from the gh-pages branch.
# Only run this once Auldwyn is ready for players to use the site.
set -euo pipefail

repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
read -r -p "Make $repo PUBLIC and publish it on GitHub Pages? Type 'yes' to continue: " answer
[ "$answer" = "yes" ] || { echo "Cancelled."; exit 1; }

gh repo edit "$repo" --visibility public --accept-visibility-change-consequences
gh api -X POST "repos/$repo/pages" -f "source[branch]=gh-pages" -f "source[path]=/" >/dev/null 2>&1 \
  || gh api -X PUT "repos/$repo/pages" -f "source[branch]=gh-pages" -f "source[path]=/" >/dev/null

echo "Done. The site appears at $(gh api "repos/$repo/pages" -q .html_url) within a few minutes."
