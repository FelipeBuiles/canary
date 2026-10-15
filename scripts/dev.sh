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
BACKEND_PYTHON="$REPO_ROOT/novel_to_comic/.venv/bin/python"
DEFAULT_CODEX_TEXT_ROUTES='{}'
DEFAULT_CODEX_IMAGE_ROUTES='[]'

MODE="api"
EXPLICIT_MODE=""
CLAUDE_CODE=false
CHECK_ONLY=false
START_DOCKER=true
REFRESH_GATEWAY=false
FIXTURE="${CANARY_MOCK_FIXTURE_PROJECT:-$DEFAULT_FIXTURE}"
CHILD_PIDS=()

usage() {
  cat <<'EOF'
Usage: ./scripts/dev.sh [options]

Start the backend and Vite client, reusing only compatible healthy services.
API (default) and Codex modes also start LiteLLM and its Postgres dependency
with Docker Compose when needed. Startup never generates or probes Codex auth.

Options:
  --codex                Enable local Codex model choices (SDK required)
  --api                  Use normal live paid API routing (default)
  --mock                 Use the zero-cost local model replay service
  --claude-code          Also offer Claude Code text models through your local
                         claude.ai login (API or Codex mode; claude CLI required)
  --fixture DIR          Completed project used by mock replay
  --no-docker            Do not automatically start missing Docker services
  --refresh-gateway      Refresh stale LiteLLM routes/handlers; rebuild only if needed
  --check                Report health only; do not start anything
  -h, --help             Show this help

Examples:
  ./scripts/dev.sh
  ./scripts/dev.sh --api
  ./scripts/dev.sh --refresh-gateway
  ./scripts/gateway.sh         # Refresh only LiteLLM, preserving credential mounts
  ./scripts/gateway.sh --check # Read-only gateway freshness check
  ./scripts/dev.sh --mock
  ./scripts/dev.sh --mock --fixture projects/my-completed-project

Mode flags are mutually exclusive. Stop an incompatible existing backend manually;
the launcher never restarts it. Flags do not re-route saved artifacts. Experimental
Codex Draw supports new editions only, five total image inputs and native output
dimensions. Select Codex models in Account → Models (dev); no route maps are
required and no API model selection is automatically redirected.
PostHog uses environment configuration; no --observability flag or local collector.
Detailed local files are opt-in with CANARY_LOCAL_DIAGNOSTICS=true. Restart
existing services manually after changing telemetry configuration.
API model settings reject aliases overridden by Codex; restart with --api to use
those selections. See docs/reference/codex-dev-capabilities.md for setup and limits.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --codex|--api|--mock)
      requested_mode="${1#--}"
      if [ -n "$EXPLICIT_MODE" ] && [ "$EXPLICIT_MODE" != "$requested_mode" ]; then
        echo "[dev] mode flags --codex, --api and --mock are mutually exclusive" >&2
        exit 2
      fi
      MODE="$requested_mode"
      EXPLICIT_MODE="$requested_mode"
      shift
      ;;
    --claude-code)
      CLAUDE_CODE=true
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
    --no-docker)
      START_DOCKER=false
      shift
      ;;
    --refresh-gateway)
      REFRESH_GATEWAY=true
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

if [ "$REFRESH_GATEWAY" = true ] && { [ "$CHECK_ONLY" = true ] || [ "$START_DOCKER" = false ] || [ "$MODE" = "mock" ]; }; then
  echo "[dev] --refresh-gateway cannot be combined with --check, --no-docker, or --mock" >&2
  exit 2
fi

source "$SCRIPT_DIR/dev_environment.sh"
report_posthog_configuration
COMPOSE_ARGS=(-f "$REPO_ROOT/docker-compose.yml")
if [ -n "${CANARY_VERTEX_CREDENTIALS_FILE:-}" ]; then
  COMPOSE_ARGS+=(-f "$REPO_ROOT/docker-compose.vertex.yml")
fi
if [ -n "${CANARY_AWS_LOGIN_CACHE_DIRECTORY:-}" ]; then
  COMPOSE_ARGS+=(-f "$REPO_ROOT/docker-compose.aws-login.yml")
fi

if [ "$CLAUDE_CODE" = true ] && [ "$MODE" = "mock" ]; then
  echo "[dev] --claude-code cannot be combined with --mock" >&2
  exit 2
fi

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

codex_sdk_installed() {
  [ -x "$BACKEND_PYTHON" ] || return 1
  "$BACKEND_PYTHON" -I -B -c '
import importlib.metadata
import sys
try:
    installed = all(
        importlib.metadata.version(package) == "0.159.0"
        for package in ("openai-codex", "openai-codex-cli-bin")
    )
except importlib.metadata.PackageNotFoundError:
    installed = False
sys.exit(0 if installed else 1)
' >/dev/null 2>&1
}

backend_healthy_for_mode() {
  local payload
  payload="$(curl --silent --show-error --fail --max-time 3 \
    "$BACKEND_URL/api/health/ready" 2>/dev/null)" || return 1
  [ -x "$BACKEND_PYTHON" ] || return 1
  printf '%s' "$payload" | "$BACKEND_PYTHON" -I -B -c '
import json
import sys
try:
    payload = json.load(sys.stdin)
    mode = sys.argv[1]
    claude_code = sys.argv[2] == "true"
    dependency = "mock_models" if mode == "mock" else "litellm"
    compatible = (
        isinstance(payload, dict)
        and payload.get("model_mode") == mode
        and payload.get("claude_code", False) is claude_code
        and payload.get("pipeline_contract") == "eight-stage-v2"
        and isinstance(payload.get("checks"), dict)
        and dependency in payload["checks"]
        and payload["checks"].get("generation_queue") == "ok"
    )
except (ValueError, TypeError):
    compatible = False
sys.exit(0 if compatible else 1)
' "$MODE" "$CLAUDE_CODE"
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local pid="${3:-}"
  local attempt=0
  while [ "$attempt" -lt 60 ]; do
    if [ "$SHUTDOWN_REQUESTED" = true ]; then return 130; fi
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
  container_id="$(docker compose "${COMPOSE_ARGS[@]}" ps -q "$service" 2>/dev/null)"
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
  docker compose "${COMPOSE_ARGS[@]}" up -d --wait "$@"
}

source "$SCRIPT_DIR/dev_lifecycle.sh"

echo "[dev] Scenewright development stack ($MODE mode)"
if [ "$MODE" = "codex" ]; then
  echo "[dev] selected routes use Codex allowance; experimental Draw: new editions, max 5 inputs, native dimensions"
elif [ "$MODE" = "api" ]; then
  echo "[dev] normal live paid API routing; Codex is disabled"
fi
if [ "$CLAUDE_CODE" = true ]; then
  echo "[dev] Claude Code choices use your claude.ai subscription (text only); runs 'claude auth status' before each call"
fi
echo

required_failed=false

if [ "$MODE" = "codex" ]; then
  if codex_sdk_installed; then
    ok "Codex SDK and bundled runtime (0.159.0; local metadata only)"
  else
    failed "Codex mode requires the optional SDK and bundled runtime pinned to 0.159.0"
    echo "[dev] Install explicitly from the repository root (the launcher never installs it):" >&2
    echo "[dev] uv pip install --python novel_to_comic/.venv/bin/python -r scripts/requirements-codex-dev.txt" >&2
    echo "[dev] Or select --api for normal paid API routing, or --mock for replay." >&2
    if [ "$CHECK_ONLY" = false ]; then
      exit 1
    fi
    required_failed=true
  fi
fi

# Every execution mode, including fixture replay, uses the same durable queue.
queue_failed=false
if [ -z "${CANARY_QUEUE_DATABASE_URL:-}" ]; then
export CANARY_QUEUE_DATABASE_URL="postgresql://canary:${CANARY_QUEUE_PASSWORD:-canary-local}@127.0.0.1:55432/canary_queue"
if docker_available; then
  if ! report_compose_service "queue-db"; then
    if [ "$CHECK_ONLY" = false ] && [ "$START_DOCKER" = true ]; then
      start_compose_services "queue-db"
    else
      required_failed=true
    fi
  fi
else
  failed "Docker queue-db is unavailable; configure an external CANARY_QUEUE_DATABASE_URL"
  required_failed=true
fi
fi
queue_failed="$required_failed"

if [ "$MODE" != "mock" ]; then
  gateway_verified=false
  gateway_http_ready=false
  if docker_available; then
    ok "Docker daemon"
    if ! report_compose_service "litellm-db"; then required_failed=true; fi
    if ! report_compose_service "litellm"; then required_failed=true; fi

    if [ "$REFRESH_GATEWAY" = true ] || { [ "$required_failed" = true ] && [ "$CHECK_ONLY" = false ] && [ "$START_DOCKER" = true ]; }; then
      if "$SCRIPT_DIR/gateway.sh"; then
        gateway_verified=true
        required_failed=false
        report_compose_service "litellm-db" || required_failed=true
        report_compose_service "litellm" || required_failed=true
      else
        required_failed=true
      fi
    fi
  else
    failed "Docker daemon is not available"
    required_failed=true
  fi

  if http_ok "$LITELLM_URL/health/liveliness"; then
    gateway_http_ready=true
    ok "LiteLLM ($LITELLM_URL)"
  elif [ "$CHECK_ONLY" = false ] && [ "$required_failed" = false ]; then
    if wait_for_http "LiteLLM" "$LITELLM_URL/health/liveliness"; then
      gateway_http_ready=true
    else
      required_failed=true
    fi
  else
    failed "LiteLLM HTTP health ($LITELLM_URL/health/liveliness)"
    required_failed=true
  fi
  if [ "$gateway_http_ready" = true ] && [ "$gateway_verified" = false ]; then
    "$SCRIPT_DIR/gateway.sh" --check || required_failed=true
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
      exec "$BACKEND_PYTHON" -c "$DEV_SERVICE_EXEC" uv run canary-mock-models --source "$FIXTURE"
    ) &
    mock_pid=$!
    CHILD_PIDS+=("$mock_pid")
    wait_for_http "Mock models" "$MOCK_URL/health/liveliness" "$mock_pid" || required_failed=true
  else
    missing "Mock models ($MOCK_URL)"
    required_failed=true
  fi
fi

if [ "$queue_failed" = true ]; then required_failed=true; fi


stop_if_requested
if backend_healthy_for_mode; then
  ok "Backend ($BACKEND_URL)"
elif http_responds "$BACKEND_URL/api/health/ready"; then
  failed "Backend ($BACKEND_URL) is already running but incompatible with $MODE mode (model_mode, pipeline contract or dependencies)"
  echo "[dev] This launcher stops nothing automatically: stop that backend manually, then rerun with --$MODE." >&2
  required_failed=true
elif [ "$CHECK_ONLY" = false ] && [ "$required_failed" = false ]; then
  "$BACKEND_PYTHON" -m novel_to_comic.server.queue_schema
  starting "backend at $BACKEND_URL"
  (
    cd "$REPO_ROOT/novel_to_comic"
    export CANARY_ENV="${CANARY_ENV-development}"
    export CANARY_CODEX_DEV_ENABLED=0
    export CANARY_CLAUDE_DEV_ENABLED=0
    if [ "$CLAUDE_CODE" = true ]; then
      export CANARY_CLAUDE_DEV_ENABLED=1
    fi
    export CANARY_MOCK_GENERATIONS_ENABLED=false
    if [ "$MODE" = "mock" ]; then
      export CANARY_MOCK_GENERATIONS_ENABLED=true
      export CANARY_MOCK_MODEL_BASE_URL="$MOCK_URL"
    elif [ "$MODE" = "codex" ]; then
      export CANARY_CODEX_DEV_ENABLED=1
      export CANARY_CODEX_DEV_TEXT_ROUTES="${CANARY_CODEX_DEV_TEXT_ROUTES-$DEFAULT_CODEX_TEXT_ROUTES}"
      export CANARY_CODEX_DEV_IMAGE_ROUTES="${CANARY_CODEX_DEV_IMAGE_ROUTES-$DEFAULT_CODEX_IMAGE_ROUTES}"
      if [ "$CANARY_CODEX_DEV_TEXT_ROUTES" = '{}' ] && [ "$CANARY_CODEX_DEV_IMAGE_ROUTES" = '[]' ]; then
        echo "[dev] Choose Codex or API models in Account → Models (dev). No legacy route overrides are active." >&2
      fi
      export CANARY_CODEX_DEV_IMAGE_REASONING_MODEL="${CANARY_CODEX_DEV_IMAGE_REASONING_MODEL-gpt-6.1-sol}"
      exec "$BACKEND_PYTHON" -c "$DEV_SERVICE_EXEC" uv run --no-sync pipeline serve --dev --projects-dir "$REPO_ROOT/projects"
    fi
    exec "$BACKEND_PYTHON" -c "$DEV_SERVICE_EXEC" uv run pipeline serve --dev --projects-dir "$REPO_ROOT/projects"
  ) &
  backend_pid=$!
  CHILD_PIDS+=("$backend_pid")
  wait_for_http "Backend" "$BACKEND_URL/api/health/ready" "$backend_pid" || required_failed=true
else
  missing "Backend ($BACKEND_URL)"
  required_failed=true
fi

stop_if_requested
if http_ok "$FRONTEND_URL"; then
  ok "Frontend ($FRONTEND_URL)"
elif [ "$CHECK_ONLY" = false ] && [ "$required_failed" = false ]; then
  starting "Vite frontend at $FRONTEND_URL"
  (
    cd "$REPO_ROOT/web"
    exec "$BACKEND_PYTHON" -c "$DEV_SERVICE_EXEC" npm run dev -- --host 127.0.0.1
  ) &
  frontend_pid=$!
  CHILD_PIDS+=("$frontend_pid")
  wait_for_http "Frontend" "$FRONTEND_URL" "$frontend_pid" || required_failed=true
else
  missing "Frontend ($FRONTEND_URL)"
  required_failed=true
fi

stop_if_requested
echo
if [ "$required_failed" = true ]; then
  failed "development stack is not ready"
  if [ "$CHECK_ONLY" = true ]; then
    echo "[dev] Stop any incompatible backend manually; run ./scripts/dev.sh --$MODE to start missing services." >&2
  fi
  exit 1
fi

echo "[dev] ready: $FRONTEND_URL"
if [ "${#CHILD_PIDS[@]}" -eq 0 ]; then
  echo "[dev] all services were already running"
  exit 0
fi

echo "[dev] press Ctrl-C to stop the processes started here; Docker dependencies stay running"
service_exit=0
wait "${CHILD_PIDS[@]}" || service_exit=$?
if [ "$SHUTDOWN_REQUESTED" = false ]; then
  signal_owned_services TERM
fi
wait_for_owned_services
if [ "$SHUTDOWN_REQUESTED" = true ]; then
  exit 130
fi
exit "$service_exit"
