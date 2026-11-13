#!/bin/bash
# Run a command with a RAM cap: polls the resident memory of the whole process tree every second and kills it
# above LIMIT_GB. macOS ignores `ulimit -v`, so this is the guard against swapping the 16 GB laptop to death.
# Usage: tools/memguard.sh LIMIT_GB command [args...]
set -u
LIMIT_GB=$1; shift
LIMIT_KB=$(awk -v g="$LIMIT_GB" 'BEGIN{printf "%d", g*1024*1024}')
"$@" &
PID=$!
PEAK=0
tree_rss() {  # sum RSS (KB) of PID and all its descendants
  local pids="$1" all="$1" kids
  while [ -n "$pids" ]; do
    kids=$(for p in $pids; do pgrep -P "$p"; done | tr '\n' ' ')
    all="$all $kids"; pids="$kids"
  done
  ps -o rss= -p $(echo $all | tr ' ' ',') 2>/dev/null | awk '{s+=$1} END{print s+0}'
}
while kill -0 $PID 2>/dev/null; do
  R=$(tree_rss $PID)
  [ "$R" -gt "$PEAK" ] && PEAK=$R
  if [ "$R" -gt "$LIMIT_KB" ]; then
    echo "memguard: RSS $((R/1024)) MB > ${LIMIT_GB} GB, killing $*" >&2
    pkill -TERM -P $PID 2>/dev/null; kill -TERM $PID 2>/dev/null; sleep 2; kill -KILL $PID 2>/dev/null
    wait $PID 2>/dev/null; exit 137
  fi
  sleep 1
done
wait $PID; RC=$?
echo "memguard: peak RSS $((PEAK/1024)) MB (limit ${LIMIT_GB} GB), exit $RC" >&2
exit $RC
