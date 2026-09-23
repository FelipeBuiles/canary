# Signal and reap only services launched by this invocation of dev.sh.
# A separate session keeps Ctrl-C with the launcher until it forwards a signal.
SHUTDOWN_REQUESTED=false
DEV_SERVICE_EXEC='import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])'

signal_owned_services() {
  local signal="$1" pid
  for pid in "${CHILD_PIDS[@]}"; do
    # Include children of uv/npm if their launcher exited while draining.
    kill "-$signal" -- "-$pid" 2>/dev/null || kill "-$signal" "$pid" 2>/dev/null || true
  done
}

owned_service_alive() {
  local pid="$1"
  kill -0 -- "-$pid" 2>/dev/null || kill -0 "$pid" 2>/dev/null
}

on_shutdown_signal() {
  if [ "$SHUTDOWN_REQUESTED" = false ]; then
    SHUTDOWN_REQUESTED=true
    echo
    echo "[dev] waiting for running jobs; press Ctrl-C again to stop now"
    signal_owned_services TERM
    return
  fi
  echo
  echo "[dev] forcing services started by this launcher to stop"
  signal_owned_services KILL
}

wait_for_owned_services() {
  local pid
  for pid in "${CHILD_PIDS[@]}"; do
    while owned_service_alive "$pid"; do
      wait "$pid" 2>/dev/null || true
      if owned_service_alive "$pid"; then sleep 0.2 || true; fi
    done
    wait "$pid" 2>/dev/null || true
  done
}

stop_if_requested() {
  if [ "$SHUTDOWN_REQUESTED" = true ]; then
    wait_for_owned_services
    exit 130
  fi
}

cleanup() {
  trap - EXIT
  if [ "${#CHILD_PIDS[@]}" -eq 0 ]; then return; fi
  if [ "$SHUTDOWN_REQUESTED" = false ]; then
    SHUTDOWN_REQUESTED=true
    echo
    echo "[dev] stopping services started by this launcher..."
    signal_owned_services TERM
  fi
  wait_for_owned_services
  trap - INT TERM
}

trap cleanup EXIT
trap on_shutdown_signal INT TERM
