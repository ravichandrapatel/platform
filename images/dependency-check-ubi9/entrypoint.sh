#!/bin/bash
# Wrapper so the action can pass args; same as original Dependency-Check_Action.
set -e
exec /usr/share/dependency-check/bin/dependency-check.sh "$@"
