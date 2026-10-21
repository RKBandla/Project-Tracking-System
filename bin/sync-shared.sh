#!/usr/bin/env bash
# Script: Sync shared backend code
# Purpose: Copy backend/_shared into every service folder as the "shared" package,
#          because each Lambda is packaged from its own folder.
# Usage: ./sync-shared.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" > /dev/null 2>&1 || exit 1; pwd -P)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/../backend" > /dev/null 2>&1 || exit 1; pwd -P)"

for req in "$BACKEND_DIR"/*/requirements.txt; do
    svc_dir="$(dirname "$req")"
    case "$(basename "$svc_dir")" in _*|.*) continue ;; esac
    rm -rf "$svc_dir/shared"
    mkdir -p "$svc_dir/shared"
    cp "$BACKEND_DIR"/_shared/*.py "$svc_dir/shared/"
    echo "INFO: Synced shared code into $(basename "$svc_dir")"
done
