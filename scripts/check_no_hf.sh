#!/usr/bin/env bash
# Fails if any Hugging Face package, import, model ID or endpoint appears in code, config or the lockfile.
set -euo pipefail
cd "$(dirname "$0")/.."

PKG='(transformers|sentence[-_]transformers|huggingface[-_]hub|tokenizers|datasets|hf[-_]transfer|safetensors)'
bad=0

# 1. Dependency declarations and lockfile
for f in pyproject.toml uv.lock; do
  [ -f "$f" ] || continue
  if grep -Eiq "^[[:space:]]*(name = )?[\"']?${PKG}[\"']?([[:space:]]*[<>=~!\",].*)?[[:space:]]*$" "$f"; then
    echo "HF package found in $f:"; grep -Ein "^[[:space:]]*(name = )?[\"']?${PKG}[\"']?" "$f"; bad=1
  fi
done

# 2. Imports, endpoints and model IDs in code, config, prompts and tests
paths=()
for d in src tests config prompts scripts; do [ -d "$d" ] && paths+=("$d"); done
if [ "${#paths[@]}" -gt 0 ]; then
  if grep -rEn --exclude=check_no_hf.sh --exclude-dir=cassettes \
      -e "^[[:space:]]*(import|from)[[:space:]]+${PKG}\b" \
      -e "huggingface\.co|hf\.co/|hf_hub|HF_TOKEN|HUGGINGFACE" \
      "${paths[@]}"; then
    bad=1
  fi
fi

if [ "$bad" -ne 0 ]; then echo "FAIL: Hugging Face usage is forbidden (see CLAUDE.md)."; exit 1; fi
echo "OK: no Hugging Face usage found."
