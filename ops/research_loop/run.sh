#!/usr/bin/env bash
# Daily research run (systemd user timer trading-research-daily.timer). One run at a time.
# The run sits inside bwrap: live-money secrets and broker credentials are hidden, the live
# checkout is read-only. systemd sandbox options are ignored for user units on this box, so
# the wall is bwrap. A probe at the start refuses to run if the wall is not there.
set -u
WT=/mnt/n/code/trading/tre-research
LIVE=/mnt/n/code/trading/trading-research-engine
LOG=/mnt/t/making-money/engine/research-daily.log
LOCK=/tmp/trading-research-daily.lock
exec 9>"$LOCK"; flock -n 9 || { echo "$(date -Is) already running" >>"$LOG"; exit 0; }
for i in $(seq 1 30); do [ -e "$WT/.git" ] && [ -d /mnt/t/making-money ] && break; sleep 10; done
[ -f ~/.config/trading-research-loop/env ] && . ~/.config/trading-research-loop/env

WALL=(--bind / / --dev-bind /dev /dev --proc /proc)
for d in "$HOME/.trading-research-engine" /mnt/c/Users/Administrator/.trading-research-engine \
         /mnt/shaka/Users/Administrator/.trading-research-engine; do
  [ -d "$d" ] && WALL+=(--tmpfs "$(realpath "$d")")
done
WALL+=(--ro-bind "$LIVE" "$LIVE" --ro-bind /mnt/n/code/trading/ctrader-connect /mnt/n/code/trading/ctrader-connect)
# git worktree metadata lives in the live checkout's .git; the run must be able to commit.
WALL+=(--bind "$LIVE/.git/worktrees" "$LIVE/.git/worktrees" --bind "$LIVE/.git/objects" "$LIVE/.git/objects" \
       --bind "$LIVE/.git/refs" "$LIVE/.git/refs" --bind "$LIVE/.git/logs" "$LIVE/.git/logs")
[ -f "$LIVE/.git/packed-refs" ] && WALL+=(--bind "$LIVE/.git/packed-refs" "$LIVE/.git/packed-refs")
# credential hides LAST, so no later directory bind re-exposes them
for f in "$LIVE/.env" "$LIVE/tokens.json" /mnt/n/code/trading/ctrader-connect/.env \
         /mnt/n/code/trading/ctrader-connect/tokens.json "$WT/.env" "$WT/tokens.json"; do
  [ -f "$f" ] && WALL+=(--ro-bind /dev/null "$(realpath "$f")")
done

probe='s=$(cat ~/.trading-research-engine/live_secret 2>/dev/null); [ -z "$s" ] || exit 11;
       ! grep -q . '"$LIVE"'/.env 2>/dev/null || exit 12; ! touch '"$LIVE"'/.wallprobe 2>/dev/null || exit 13; exit 0'
if ! bwrap "${WALL[@]}" bash -c "$probe"; then
  echo "$(date -Is) WALL PROBE FAILED rc=$?; not running" >>"$LOG"; rm -f "$LIVE/.wallprobe"; exit 1
fi

cd "$WT" || exit 1
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 GCM_INTERACTIVE=never GIT_TERMINAL_PROMPT=0
PROMPT="$(sed "s/\$(date)/$(date +%F)/" ops/research_loop/prompt.md)
OWNER_EMAIL=${OWNER_EMAIL:-unset}"
echo "=== $(date -Is) start (walled)" >>"$LOG"
timeout 9000 nice -n 10 bwrap "${WALL[@]}" --chdir "$WT" claude -p "$PROMPT" --model claude-opus-5-5 \
  --dangerously-skip-permissions --add-dir "$LIVE" --add-dir /mnt/t/making-money >>"$LOG" 2>&1
rc=$?
echo "=== $(date -Is) end rc=$rc" >>"$LOG"
