#!/usr/bin/env bash
# Build one zip per skill in dist/, ready to upload in claude.ai (Settings > Capabilities > Skills).
# Claude Code users do not need this: they install the whole plugin with /plugin install.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
out="$root/dist"
rm -rf "$out" && mkdir -p "$out"

for dir in "$root"/skills/*/; do
  name="$(basename "$dir")"
  [ -f "$dir/SKILL.md" ] || continue
  (cd "$root/skills" && zip -qr "$out/$name.zip" "$name" -x '*/__pycache__/*' '*.DS_Store')
  echo "built dist/$name.zip"
done

echo
echo "Upload safety-kb.zip first (every department skill depends on it), then the department skills you want."
