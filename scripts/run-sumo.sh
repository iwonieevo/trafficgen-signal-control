
#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 || ( $# -eq 2 && "$2" != "gui" ) ]]; then
    echo "Usage: $0 <scenario> [gui]" >&2
    exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCENARIO_DIR="$ROOT/sumo/scenarios/$1"
MODE="sumo"

[[ "${2:-}" == "gui" ]] && MODE="sumo-gui"

# Find scenario configuration
shopt -s nullglob
CONFIGS=("$SCENARIO_DIR"/*.sumocfg)

if (( ${#CONFIGS[@]} != 1 )); then
    echo "Expected exactly one .sumocfg file in: $SCENARIO_DIR" >&2
    exit 1
fi

# Resolve SUMO installation
PYTHON="$ROOT/.venv/bin/python"

if [[ -x "$PYTHON" ]] &&
   SUMO_HOME="$("$PYTHON" -c 'import sumo; print(sumo.SUMO_HOME)' 2>/dev/null)"; then
    export SUMO_HOME
    EXECUTABLE="$SUMO_HOME/bin/$MODE"
else
    EXECUTABLE="$(command -v "$MODE" || true)"
fi

if [[ ! -x "$EXECUTABLE" ]]; then
    echo "SUMO executable not found: $MODE" >&2
    exit 1
fi

exec "$EXECUTABLE" -c "${CONFIGS[0]}"

