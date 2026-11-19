#!/usr/bin/env bash
# Daily research run (systemd user timer trading-research-daily.timer). One run at a time.
set -u
WT=/mnt/n/code/trading/tre-research
LOG=/mnt/t/making-money/engine/research-daily.log
LOCK=/tmp/trading-research-daily.lock
exec 9>"$LOCK"; flock -n 9 || { echo "$(date -Is) already running" >>"$LOG"; exit 0; }
for i in $(seq 1 30); do [ -d "$WT/.git" ] || [ -f "$WT/.git" ] && [ -d /mnt/t/making-money ] && break; sleep 10; done
cd "$WT" || exit 1
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 GCM_INTERACTIVE=never GIT_TERMINAL_PROMPT=0
PROMPT="$(sed "s/\$(date)/$(date +%F)/" ops/research_loop/prompt.md)"
echo "=== $(date -Is) start" >>"$LOG"
timeout 9000 nice -n 10 claude -p "$PROMPT" --model claude-opus-5-5 \
  --dangerously-skip-permissions --add-dir /mnt/n/code/trading/trading-research-engine \
  --add-dir /mnt/t/making-money >>"$LOG" 2>&1
echo "=== $(date -Is) end rc=$?" >>"$LOG"
