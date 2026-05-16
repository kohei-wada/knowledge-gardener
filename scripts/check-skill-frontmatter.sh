#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

fail=0
for f in skills/*/SKILL.md; do
  [ -f "$f" ] || continue

  fm=$(awk '/^---$/{n++; next} n==1{print} n>=2{exit}' "$f")

  if ! grep -q '^name:' <<<"$fm"; then
    echo "Missing 'name:' in frontmatter: $f" >&2
    fail=1
  fi

  if ! grep -q '^description:' <<<"$fm"; then
    echo "Missing 'description:' in frontmatter: $f" >&2
    fail=1
  fi
done

exit $fail
