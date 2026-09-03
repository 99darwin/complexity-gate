#!/bin/sh
# Runs check_complexity.py with the hook's dedicated venv when present, else the
# ambient python3 (in which case the checker degrades to a "lizard missing" notice).
# Resolves paths relative to this script so it works from any CWD.
dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
if [ -x "$dir/.venv/bin/python" ]; then
  py="$dir/.venv/bin/python"
else
  py=python3
fi
exec "$py" "$dir/check_complexity.py" "$@"
