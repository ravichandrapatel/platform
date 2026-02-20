#!/bin/bash
# ARC graceful stop: unregister runner and handle SIGTERM. No container-runtime checks.
source /usr/bin/logger.sh 2>/dev/null || true

RUNNER_GRACEFUL_STOP_TIMEOUT=${RUNNER_GRACEFUL_STOP_TIMEOUT:-15}
RUNNER_HOME=${RUNNER_HOME:-/home/runner}

graceful_stop() {
  log.notice "Executing graceful SIGTERM handler."

  if ! pushd "${RUNNER_HOME}" 2>/dev/null; then
    log.error "Failed to pushd ${RUNNER_HOME}"
    exit 1
  fi

  log.notice "Waiting for the runner to register first."
  while ! [ -f "${RUNNER_HOME}/.runner" ]; do
    sleep 1
  done
  log.notice "Runner registered."

  if ! "${RUNNER_HOME}/config.sh" remove --token "${RUNNER_TOKEN}" 2>/dev/null; then
    i=0
    log.notice "Waiting for RUNNER_GRACEFUL_STOP_TIMEOUT=$RUNNER_GRACEFUL_STOP_TIMEOUT seconds."
    while [[ $i -lt $RUNNER_GRACEFUL_STOP_TIMEOUT ]]; do
      sleep 1
      if ! pgrep Runner.Listener > /dev/null; then
        log.notice "Runner agent stopped before timeout."
        break
      fi
      i=$((i + 1))
    done
  fi

  popd || true

  if pgrep Runner.Listener > /dev/null; then
    runner_listener_pid=$(pgrep Runner.Listener)
    log.notice "Sending SIGTERM to runner agent ($runner_listener_pid)."
    kill -TERM "$runner_listener_pid" 2>/dev/null || true
    log.notice "Waiting for runner agent to stop."
    while pgrep Runner.Listener > /dev/null; do
      sleep 1
    done
  fi

  log.notice "Runner process exited."
  if [ -n "${RUNNER_INIT_PID:-}" ]; then
    wait "$RUNNER_INIT_PID" 2>/dev/null || :
  fi
  log.notice "Graceful stop completed."
}
