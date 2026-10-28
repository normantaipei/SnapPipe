#!/bin/bash
# Meta Model API 實測（說明見 meta_api_test.py 開頭）。用 worker 的 venv；第一次會自動安裝。
set -e
REPO=$(cd "$(dirname "$0")/../.." && pwd)
command -v exiftool >/dev/null || { echo "需要 exiftool（brew install exiftool / apt install libimage-exiftool-perl）"; exit 1; }
"$REPO/worker/.venv/bin/python" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null || "$REPO/worker/setup.sh"
exec "$REPO/worker/.venv/bin/python" "$REPO/tests/meta_api/meta_api_test.py" "$@"
