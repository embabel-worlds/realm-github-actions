#!/bin/sh
# Ground-truth verification for realm-github-actions. Runs the ladder in tests/verify.py:
#   L0 GitHub itself   — the reference figures, computed from the REST API directly
#   L1 traversal       — kg execute over the realm's join, exact equality with L0
#   L2 every view      — every view, real params, figures reconciled to L0 to the row
#   L3 the NL battery  — tests/questions.yml through the ask surface, adversarial half x3
#   L5 app assets      — the app is served
# Exit nonzero on any drift.
#
#   GH_TOKEN=... EMBABEL_AUTH=user:pass APPLIANCE=http://127.0.0.1:11043 sh tests/verify.sh [owner/repo [owner/repo ...]]
# The first repository takes the per-repository checks; the fleet checks cover every one named.
set -e
cd "$(dirname "$0")/.."
exec python3 tests/verify.py "$@"
