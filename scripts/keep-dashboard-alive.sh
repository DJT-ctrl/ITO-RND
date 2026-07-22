#!/usr/bin/env bash
# Keep the Streamlit dashboard running across crashes / reloads.
# Detach from the terminal with: scripts/keep-dashboard-alive.sh --detach

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STREAMLIT="$ROOT/.venv/bin/streamlit"
LOG="${ITO_DASHBOARD_LOG:-/tmp/ito-dashboard-8501.log}"
PIDFILE="${ITO_DASHBOARD_PID:-/tmp/ito-dashboard-8501.pid}"
PORT="${ITO_DASHBOARD_PORT:-8501}"

if [[ ! -x "$STREAMLIT" ]]; then
  echo "Missing .venv — run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

is_listening() {
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1
}

stop_existing() {
  if [[ -f "$PIDFILE" ]]; then
    old_pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "${old_pid:-}" ]] && kill -0 "$old_pid" 2>/dev/null; then
      kill "$old_pid" 2>/dev/null || true
      sleep 1
      kill -9 "$old_pid" 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
  fi
  # Clear any orphaned listener on the port
  if is_listening; then
    pids="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true)"
    if [[ -n "${pids:-}" ]]; then
      # shellcheck disable=SC2086
      kill $pids 2>/dev/null || true
      sleep 1
    fi
  fi
}

run_loop() {
  echo $$ > "$PIDFILE"
  echo "[$(date '+%H:%M:%S')] Dashboard keeper started (pid $$) → http://localhost:$PORT"
  echo "[$(date '+%H:%M:%S')] Logs: $LOG"

  while true; do
    echo "[$(date '+%H:%M:%S')] Starting Streamlit on :$PORT" | tee -a "$LOG"
    set +e
    "$STREAMLIT" run dashboard/app.py \
      --server.headless true \
      --server.address localhost \
      --server.port "$PORT" \
      --server.fileWatcherType poll \
      >>"$LOG" 2>&1
    code=$?
    set -e
    echo "[$(date '+%H:%M:%S')] Streamlit exited (code $code); restarting in 2s" | tee -a "$LOG"
    sleep 2
  done
}

if [[ "${1:-}" == "--detach" ]]; then
  stop_existing
  # Detach from the controlling terminal / IDE shell so cleanup cannot kill it.
  # Prefer a new session (Linux setsid / Python start_new_session); fall back to nohup.
  if command -v setsid >/dev/null 2>&1; then
    setsid bash "$0" --foreground </dev/null >>"$LOG" 2>&1 &
  elif command -v python3 >/dev/null 2>&1; then
    python3 - "$0" <<'PY' >>"$LOG" 2>&1 &
import os, sys, subprocess
script = sys.argv[1]
subprocess.Popen(
    ["bash", script, "--foreground"],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    start_new_session=True,
    cwd=os.path.dirname(os.path.dirname(os.path.abspath(script))) or ".",
)
PY
  else
    nohup bash "$0" --foreground </dev/null >>"$LOG" 2>&1 &
  fi
  disown 2>/dev/null || true
  # Give Streamlit a moment to bind the port
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if is_listening; then
      echo "Dashboard up at http://localhost:$PORT"
      echo "PID file: $PIDFILE"
      echo "Log: $LOG"
      exit 0
    fi
    sleep 1
  done
  echo "Dashboard failed to bind :$PORT — see $LOG"
  tail -n 40 "$LOG" || true
  exit 1
fi

if [[ "${1:-}" == "--stop" ]]; then
  stop_existing
  echo "Dashboard stopped"
  exit 0
fi

if [[ "${1:-}" == "--foreground" || "${1:-}" == "" ]]; then
  run_loop
fi

echo "Usage: $0 [--detach|--stop|--foreground]"
exit 1
