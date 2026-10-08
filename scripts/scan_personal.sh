#!/bin/sh
# SEC-1: thin wrapper for the personal-data scanner (see scan_personal.py).
# Advisory by default (exit 0 = report only); --strict fails on findings.
exec python3 "$(dirname "$0")/scan_personal.py" "$@"
