#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

if [ $# -ne 1 ]; then
  echo "Usage: $0 <new-version>" >&2
  echo "  Example: $0 0.5.2" >&2
  exit 1
fi

NEW="$1"

if ! [[ "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Invalid version (expected X.Y.Z): $NEW" >&2
  exit 1
fi

update_json() {
  local file="$1"
  local jq_expr="$2"
  local tmp
  tmp=$(mktemp)
  jq --arg v "$NEW" "$jq_expr" "$file" > "$tmp"
  mv "$tmp" "$file"
}

update_json package.json '.version = $v'
update_json .claude-plugin/plugin.json '.version = $v'
update_json .claude-plugin/marketplace.json '.plugins[0].version = $v'

scripts/check-version-sync.sh

echo "Bumped to $NEW. To ship:"
echo "  git add package.json .claude-plugin/plugin.json .claude-plugin/marketplace.json"
echo "  git commit -m 'chore: bump version to $NEW'"
echo "  git push"
