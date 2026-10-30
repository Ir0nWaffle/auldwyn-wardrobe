#!/usr/bin/env bash
# Push the built site (web/) to the gh-pages branch, which GitHub Pages serves.
# The branch is replaced each time so old 3D packs don't pile up in history.
# Run `docker compose run --rm build` first if the game files changed.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f web/3d/index.json ] || { echo "web/3d is missing. Run: docker compose run --rm build" >&2; exit 1; }

remote=$(git remote get-url origin)
source_rev=$(git rev-parse --short HEAD)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

cp -r web/. "$tmp/"
touch "$tmp/.nojekyll"   # serve files as-is, no Jekyll processing

git -C "$tmp" init -q -b gh-pages
git -C "$tmp" config user.name "$(git config user.name)"
git -C "$tmp" config user.email "$(git config user.email)"
git -C "$tmp" add -A
git -C "$tmp" commit -q -m "Site build from main@$source_rev"
git -C "$tmp" push -q --force "$remote" gh-pages

echo "Pushed site from main@$source_rev to gh-pages."
