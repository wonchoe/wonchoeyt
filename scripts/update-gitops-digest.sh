#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <gitops-repo-path> <image-ref>" >&2
  exit 1
fi

gitops_repo="$1"
image_ref="$2"

files=(
  "$gitops_repo/ytld/base/dep.yaml"
  "$gitops_repo/ytld/base/cookie-refresher-cronjob.yaml"
)

for file in "${files[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "Missing file: $file" >&2
    exit 1
  fi

  python3 - "$file" "$image_ref" <<'PY'
import pathlib
import re
import sys

file_path = pathlib.Path(sys.argv[1])
image_ref = sys.argv[2]

content = file_path.read_text()
updated = re.sub(r'docker\.io/wonchoe/ytdl-bot@sha256:[a-f0-9]+', image_ref, content)
file_path.write_text(updated)
PY

  if ! grep -Fq "$image_ref" "$file"; then
    echo "Failed to update image reference in $file" >&2
    exit 1
  fi
done

printf 'Updated GitOps image reference to %s\n' "$image_ref"