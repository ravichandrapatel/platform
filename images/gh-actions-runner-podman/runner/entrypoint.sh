#!/bin/bash
# ARC entrypoint: run startup under dumb-init and handle graceful stop.
# RUNNER_HOME defaults to /home/runner (runner and k8s tools live only there).

source /usr/bin/logger.sh
source /usr/bin/graceful-stop.sh
trap graceful_stop TERM

RUNNER_HOME=${RUNNER_HOME:-/home/runner}

dumb-init bash <<'SCRIPT' &
source /usr/bin/logger.sh
/usr/bin/startup.sh
SCRIPT

RUNNER_INIT_PID=$!
log.notice "Runner init started with pid $RUNNER_INIT_PID"
wait $RUNNER_INIT_PID
log.notice "Runner init exited. Exiting so the container/pod can be GC'ed."

if [ -f "${RUNNER_HOME}/.runner" ]; then
  echo "Removing the .runner file"
  rm -f "${RUNNER_HOME}/.runner"
fi

trap - TERM
