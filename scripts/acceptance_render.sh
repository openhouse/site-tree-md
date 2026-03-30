#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out_dir="${1:-$repo_root/trial-run}"

python -m pip install -e "$repo_root"
python -m site_tree_md "https://smallbizunited.com/" \
  --output-dir "$out_dir" \
  --max-pages 200 \
  --delay 0.5 \
  --verbose \
  --render-mode auto
