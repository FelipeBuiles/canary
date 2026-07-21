#!/usr/bin/env bash
# Start the Scenewright development stack from any working directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_URL="${CANARY_BACKEND_URL:-http://127.0.0.1:8000}"
FRONTEND_URL="${CANARY_FRONTEND_URL:-http://127.0.0.1:5173}"
MOCK_URL="${CANARY_MOCK_MODEL_BASE_URL:-http://127.0.0.1:4010}"
LITELLM_URL="${LITELLM_BASE_URL:-http://127.0.0.1:4000}"
DEFAULT_FIXTURE="$REPO_ROOT/projects/63f06b92-a5c6-4f5b-b0e5-c330abe49982/the-call-of-cthulhu"

MODE="live"
CHECK_ONLY=false
OBSERVABILITY=false
START_DOCKER=true
FIXTURE="${CANARY_MOCK_FIXTURE_PROJECT:-$DEFAULT_FIXTURE}"
CHILD_PIDS=()

usage() {
  cat <<'EOF'
Usage: ./scripts/dev.sh [options]

Start the backend and Vite client, reusing services that are already healthy.
In live mode the launcher also starts LiteLLM and its Postgres dependency with
Docker Compose when needed.

Options:
  --mock                 Use the zero-cost local model replay service
  --fixture DIR          Completed project used by mock replay
  --observability        Also start/check the optional Langfuse stack
  --no-docker            Do not automatically start missing Docker services
  --check                Report health only; do not start anything
  -h, --help             Show this help

Examples:
  ./scripts/dev.sh
  ./scripts/dev.sh --mock
  ./scripts/dev.sh --mock --fixture projects/my-completed-project
  ./scripts/dev.sh --check --observability
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --mock)
      MODE="mock"
      shift
      ;;
    --fixture)
      if [ "$#" -lt 2 ]; then
        echo "[dev] --fixture requires a directory" >&2
        exit 2
      fi
      FIXTURE="$2"
      shift 2
      ;;
    --observability)
      OBSERVABILITY=true
      shift
      ;;
    --no-docker)
      START_DOCKER=false
      shift
      ;;
    --check)
      CHECK_ONLY=true
      START_DOCKER=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[dev] unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ "${FIXTURE#/}" = "$FIXTURE" ]; then
  FIXTURE="$REPO_ROOT/$FIXTURE"
fi

ok() { printf '\033[32m%-10s\033[0m %s\n' "healthy" "$1"; }
missing() { printf '\033[33m%-10s\033[0m %s\n' "missing" "$1"; }
failed() { printf '\033[31m%-10s\033[0m %s\n' "unhealthy" "$1" >&2; }
starting() { printf '\033[36m%-10s\033[0m %s\n' "starting" "$1"; }

http_ok() {
  curl --silent --show-error --fail --max-time 3 "$1" >/dev/null 2>&1
}

http_responds() {
  curl --silent --show-error --max-time 3 "$1" >/dev/null 2>&1
}

backend_healthy_for_mode() {
  local payload
  payload="$(curl --silent --show-error --fail --max-time 3 \
    "$BACKEND_URL/api/health/ready" 2>/dev/null)" || return 1
  if [ "$MODE" = "mock" ]; then
    printf '%s' "$payload" | grep -q '"mock_models"'
  else
    printf '%s' "$payload" | grep -q '"litellm"'
  fi
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local pid="${3:-}"
  local attempt=0
  while [ "$attempt" -lt 60 ]; do
    if http_ok "$url"; then
      ok "$name ($url)"
      return 0
    fi
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
      failed "$name exited before becoming healthy"
      return 1
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
  failed "$name did not become healthy within 60 seconds ($url)"
  return 1
}

docker_available() {
  command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
}

compose_service_healthy() {
  local service="$1"
  local container_id
  local status
  container_id="$(docker compose -f "$REPO_ROOT/docker-compose.yml" ps -q "$service" 2>/dev/null)"
  [ -n "$container_id" ] || return 1
  status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null)"
  [ "$status" = "healthy" ] || [ "$status" = "running" ]
}

report_compose_service() {
  local service="$1"
  if compose_service_healthy "$service"; then
    ok "Docker: $service"
    return 0
  fi
  missing "Docker: $service"
  return 1
}

start_compose_services() {
  starting "Docker services: $*"
  docker compose -f "$REPO_ROOT/docker-compose.yml" up -d --wait "$@"
}

cleanup() {
  local pid
  if [ "${#CHILD_PIDS[@]}" -gt 0 ]; then
    echo
    echo "[dev] stopping services started by this launcher..."
    for pid in "${CHILD_PIDS[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
    wait "${CHILD_PIDS[@]}" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

echo "[dev] Scenewright development stack ($MODE mode)"
echo

required_failed=false

if [ "$MODE" = "live" ]; then
  if docker_available; then
    ok "Docker daemon"
    if ! report_compose_service "litellm-db"; then required_failed=true; fi
    if ! report_compose_service "litellm"; then required_failed=true; fi

    if [ "$required_failed" = true ] && [ "$CHECK_ONLY" = false ] && [ "$START_DOCKER" = true ]; then
      start_compose_services "litellm"
      required_failed=false
      report_compose_service "litellm-db" || required_failed=true
      report_compose_service "litellm" || required_failed=true
    fi
  else
    failed "Docker daemon is not available"
    required_failed=true
  fi

  if http_ok "$LITELLM_URL/health/liveliness"; then
    ok "LiteLLM ($LITELLM_URL)"
  elif [ "$CHECK_ONLY" = false ] && [ "$required_failed" = false ]; then
    wait_for_http "LiteLLM" "$LITELLM_URL/health/liveliness" || required_failed=true
  else
    failed "LiteLLM HTTP health ($LITELLM_URL/health/liveliness)"
    required_failed=true
  fi
else
  if [ ! -d "$FIXTURE" ] || [ ! -f "$FIXTURE/config.yaml" ]; then
    failed "mock fixture is not a Canary project: $FIXTURE"
    required_failed=true
  fi

  if http_ok "$MOCK_URL/health/liveliness"; then
    ok "Mock models ($MOCK_URL)"
  elif [ "$CHECK_ONLY" = false ] && [ "$required_failed" = false ]; then
    starting "mock models from $FIXTURE"
    (
      cd "$REPO_ROOT/novel_to_comic"
      exec uv run canary-mock-models --source "$FIXTURE"
    ) &
    mock_pid=$!
    CHILD_PIDS+=("$mock_pid")
    wait_for_http "Mock models" "$MOCK_URL/health/liveliness" "$mock_pid" || required_failed=true
  else
    missing "Mock models ($MOCK_URL)"
    required_failed=true
  fi
fi

if [ "$OBSERVABILITY" = true ]; then
  observability_failed=false
  if docker_available; then
    for service in langfuse-postgres langfuse-clickhouse langfuse-redis langfuse-minio langfuse-worker langfuse-web; do
      report_compose_service "$service" || observability_failed=true
    done
    if [ "$observability_failed" = true ] && [ "$CHECK_ONLY" = false ] && [ "$START_DOCKER" = true ]; then
      start_compose_services "langfuse-web" "langfuse-worker"
    fi
  else
    failed "Docker is required for the optional Langfuse stack"
    required_failed=true
  fi
fi

if backend_healthy_for_mode; then
  ok "Backend ($BACKEND_URL)"
elif http_responds "$BACKEND_URL/api/health/ready"; then
  failed "Backend is already running but is unhealthy or in the wrong mode"
  echo "[dev] Stop the process on port 8000 before switching between live and mock mode." >&2
  required_failed=true
elif [ "$CHECK_ONLY" = false ] && [ "$required_failed" = false ]; then
  starting "backend at $BACKEND_URL"
  (
    cd "$REPO_ROOT/novel_to_comic"
    if [ "$MODE" = "mock" ]; then
      exec env CANARY_MOCK_GENERATIONS_ENABLED=true \
        CANARY_MOCK_MODEL_BASE_URL="$MOCK_URL" \
        uv run pipeline serve --dev --projects-dir "$REPO_ROOT/projects"
    else
      exec uv run pipeline serve --dev --projects-dir "$REPO_ROOT/projects"
    fi
  ) &
  backend_pid=$!
  CHILD_PIDS+=("$backend_pid")
  wait_for_http "Backend" "$BACKEND_URL/api/health/ready" "$backend_pid" || required_failed=true
else
  missing "Backend ($BACKEND_URL)"
  required_failed=true
fi

if http_ok "$FRONTEND_URL"; then
  ok "Frontend ($FRONTEND_URL)"
elif [ "$CHECK_ONLY" = false ] && [ "$required_failed" = false ]; then
  starting "Vite frontend at $FRONTEND_URL"
  (
    cd "$REPO_ROOT/web"
    exec npm run dev -- --host 127.0.0.1
  ) &
  frontend_pid=$!
  CHILD_PIDS+=("$frontend_pid")
  wait_for_http "Frontend" "$FRONTEND_URL" "$frontend_pid" || required_failed=true
else
  missing "Frontend ($FRONTEND_URL)"
  required_failed=true
fi

echo
if [ "$required_failed" = true ]; then
  failed "development stack is not ready"
  if [ "$CHECK_ONLY" = true ]; then
    if [ "$MODE" = "mock" ]; then
      echo "[dev] Run ./scripts/dev.sh --mock to start missing services." >&2
    else
      echo "[dev] Run ./scripts/dev.sh to start missing services." >&2
    fi
  fi
  exit 1
fi

echo "[dev] ready: $FRONTEND_URL"
if [ "${#CHILD_PIDS[@]}" -eq 0 ]; then
  echo "[dev] all services were already running"
  exit 0
fi

echo "[dev] press Ctrl-C to stop the processes started here; Docker dependencies stay running"
wait "${CHILD_PIDS[@]}"
