# Shared by the native and Docker development launchers (source at top level).
# Precedence: exported shell values > web/.env.local > web/.env > root .env.
# Restore shell values even when explicitly empty (an intentional opt-out).
_CANARY_INHERITED_EXPORTS="$(export -p)"
set -a
for _CANARY_ENV_FILE in "$REPO_ROOT/.env" "$REPO_ROOT/web/.env" "$REPO_ROOT/web/.env.local"; do
  if [ -f "$_CANARY_ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$_CANARY_ENV_FILE"
  fi
done
set +a
eval "$_CANARY_INHERITED_EXPORTS"
unset _CANARY_INHERITED_EXPORTS _CANARY_ENV_FILE

# Derive public browser settings only when absent; explicit empty values win.
export VITE_POSTHOG_PROJECT_TOKEN="${VITE_POSTHOG_PROJECT_TOKEN-${POSTHOG_PROJECT_TOKEN-}}"
export VITE_POSTHOG_HOST="${VITE_POSTHOG_HOST-${POSTHOG_HOST-}}"
export CANARY_ENV="${CANARY_ENV-development}"
export VITE_CANARY_ENV="${VITE_CANARY_ENV-$CANARY_ENV}"
# A local build is attributable to its checkout and a unique launcher session.
# A fresh session distinguishes edits made between restarts, including untracked code.
export CANARY_VERSION="${CANARY_VERSION-$(git -C "$REPO_ROOT" describe --always --dirty --abbrev=12 2>/dev/null || echo local)-$(date -u +%Y%m%dT%H%M%S)-$$}"
export VITE_CANARY_VERSION="${VITE_CANARY_VERSION-$CANARY_VERSION}"
export CANARY_LOCAL_DIAGNOSTICS="${CANARY_LOCAL_DIAGNOSTICS-false}"

report_posthog_configuration() {
  local label token host
  for label in backend browser; do
    if [ "$label" = backend ]; then
      token="${POSTHOG_PROJECT_TOKEN-}"; host="${POSTHOG_HOST-}"
    else
      token="${VITE_POSTHOG_PROJECT_TOKEN-}"; host="${VITE_POSTHOG_HOST-}"
    fi
    if [ -n "$token" ] && { [ "$host" = https://us.i.posthog.com ] || [ "$host" = https://eu.i.posthog.com ]; }; then
      echo "[dev] PostHog $label: configured (delivery not checked)"
    elif [ -n "$token$host" ]; then
      echo "[dev] PostHog $label: disabled (token and US/EU ingestion host required)"
    else
      echo "[dev] PostHog $label: disabled"
    fi
  done
  echo "[dev] Detailed local diagnostics: $CANARY_LOCAL_DIAGNOSTICS"
}
