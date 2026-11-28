#!/usr/bin/env bash
# Rewrites Formula/codo.rb and bucket/codo.json for a release.
#   update-packages.sh <version without v> <path to SHA256SUMS>
set -euo pipefail
ver="$1"; sums="$2"
sha() { awk -v f="$1" '$2 == f {print $1}' "$sums"; }
f=Formula/codo.rb
sed -i.bak -E "s/^  version \"[^\"]*\"/  version \"$ver\"/; s#/download/v[0-9][^/]*/#/download/v$ver/#g" "$f"
for n in codo-macos-arm64 codo-macos-x64 codo-linux-arm64 codo-linux-x64; do
  s="$(sha "$n")"; [ -n "$s" ] || { echo "no sum for $n"; exit 1; }
  awk -v n="$n" -v s="$s" '{ if (hit && $1 == "sha256") { sub(/"[0-9a-f]+"/, "\"" s "\""); hit=0 } if (index($0, "/" n "\"")) hit=1; print }' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
done
b=bucket/codo.json
w="$(sha codo-windows-x64.exe)"; [ -n "$w" ] || { echo "no sum for windows"; exit 1; }
python3 - "$b" "$ver" "$w" <<'PY'
import json, sys
p, ver, h = sys.argv[1:]
d = json.load(open(p))
d["version"] = ver
a = d["architecture"]["64bit"]
a["url"] = f"https://github.com/DomaAI/Codo/releases/download/v{ver}/codo-windows-x64.exe#/codo.exe"
a["hash"] = h
open(p, "w").write(json.dumps(d, indent=4) + "\n")
PY
rm -f "$f.bak"
