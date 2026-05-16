#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

pkg=$(jq -r '.version' package.json)
plug=$(jq -r '.version' .claude-plugin/plugin.json)
mkt=$(jq -r '.plugins[0].version' .claude-plugin/marketplace.json)

if [ "$pkg" = "$plug" ] && [ "$pkg" = "$mkt" ]; then
  exit 0
fi

{
  echo "Version mismatch across files:"
  echo "  package.json:                    $pkg"
  echo "  .claude-plugin/plugin.json:      $plug"
  echo "  .claude-plugin/marketplace.json: $mkt"
} >&2
exit 1
