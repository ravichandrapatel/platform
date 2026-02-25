#!/usr/bin/env bash
set -Eeuo pipefail
source /usr/bin/logger.sh 2>/dev/null || true
log.debug "Running ARC Job Completed Hooks"
for hook in /etc/arc/hooks/job-completed.d/*; do
  [ -f "$hook" ] && [ -x "$hook" ] && log.debug "Running hook: $hook" && "$hook" "$@" || true
done
