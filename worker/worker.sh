#!/bin/bash
cd "$(dirname "$0")"
.venv/bin/python -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null || ./setup.sh
exec .venv/bin/python worker.py "$@"
