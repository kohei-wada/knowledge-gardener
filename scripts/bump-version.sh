#!/usr/bin/env bash
#
# bump-version.sh — sync-bump the version across package.json,
# .claude-plugin/plugin.json, and .claude-plugin/marketplace.json,
# then commit and create an annotated tag.
#
# Pushing the commit + tag is left to the operator. The release.yml
# workflow turns the pushed tag into a GitHub release with
# auto-generated notes.
#
# Usage:
#   scripts/bump-version.sh patch       # 1.4.0 -> 1.4.1
#   scripts/bump-version.sh minor       # 1.4.0 -> 1.5.0
#   scripts/bump-version.sh major       # 1.4.0 -> 2.0.0
#   scripts/bump-version.sh 1.4.2       # explicit

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

usage() {
  sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'
}

if [[ $# -ne 1 ]]; then
  usage >&2
  exit 1
fi

current=$(jq -r '.version' package.json)
IFS='.' read -r maj min pat <<<"$current"

case "$1" in
  patch) new="$maj.$min.$((pat + 1))" ;;
  minor) new="$maj.$((min + 1)).0" ;;
  major) new="$((maj + 1)).0.0" ;;
  *)
    if [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      new="$1"
    else
      echo "Unknown bump: $1" >&2
      usage >&2
      exit 1
    fi
    ;;
esac

if [[ "$current" == "$new" ]]; then
  echo "Already at $current — nothing to do." >&2
  exit 1
fi

# Refuse to bump on a dirty tree — a half-staged change would land in the
# release commit.
if ! git diff-index --quiet HEAD --; then
  echo "Working tree has uncommitted changes — aborting." >&2
  git status --short >&2
  exit 1
fi

bump_json_field() {
  local file="$1" path="$2"
  local tmp
  tmp=$(mktemp)
  jq --arg v "$new" "$path = \$v" "$file" >"$tmp"
  mv "$tmp" "$file"
}

bump_json_field package.json '.version'
bump_json_field .claude-plugin/plugin.json '.version'
bump_json_field .claude-plugin/marketplace.json '.plugins[0].version'

scripts/check-version-sync.sh

git add package.json .claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore(release): bump $current -> $new"
git tag -a "v$new" -m "Release v$new"

cat <<EOF

Bumped $current -> $new
Committed: $(git rev-parse --short HEAD)
Tagged:    v$new

Next:
  git push origin main "v$new"

release.yml will create the GitHub release with auto-generated notes
once the tag arrives.
EOF
