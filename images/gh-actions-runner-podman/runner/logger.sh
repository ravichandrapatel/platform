#!/usr/bin/env bash
# Logger for ARC-style runner. Sourced by other scripts.
# See: https://github.com/actions/actions-runner-controller/blob/master/runner/logger.sh

__log() {
  local color instant level
  color=${1:?missing required argument}
  shift
  level=${FUNCNAME[1]}
  level=${level#log.}
  level=${level^^}
  if [[ ! -v "LOG_${level}_DISABLED" ]]; then
    instant=$(date '+%F %T.%-3N' 2>/dev/null || :)
    if [[ -v NO_COLOR ]]; then
      printf -- '%s %s --- %s\n' "$instant" "$level" "$*" 1>&2 || :
    else
      printf -- '\033[0;%dm%s %s --- %s\033[0m\n' "$color" "$instant" "$level" "$*" 1>&2 || :
    fi
  fi
}

log.debug () { __log 37 "$@"; }
log.notice () { __log 34 "$@"; }
log.warning () { __log 33 "$@"; }
log.error () { __log 31 "$@"; }
log.success () { __log 32 "$@"; }
