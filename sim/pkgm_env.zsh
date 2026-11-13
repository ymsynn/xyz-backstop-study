# Engine settings of the proposal's mark, shared by every run script. A mark-run tag names one combination:
#   pkgm3<k|q|r><seconds>   the three-vote mark with an average over <seconds>:
#                           k = the average is never brought back to the mark,
#                           q = unless xyz's book alone decided the previous mark (the proposal is pkgm3q1800; frozen 2026-11-11),
#                           r = always
# The settings printed below are the whole rule: removing any one of them changes the replay, and the run scripts pass
# nothing else for it (checked 2026-11-12: byte-identical to the final run on eight tests). The liquidation sizing is
# separate (liq_restore=2 restore_big=1 = the cut-back). Earlier candidates' settings: archive/archive/sim/pkgm_env_all.zsh.
pkgm_extra() {
  local mk=${1%s20} r=()
  # an unknown tag must stop the run, not fall back to today's rules: the engine refuses this value
  [[ $mk == pkgm3[kqr]<-> ]] || { print -r -- "MARK3=unknown_mark_$1"; return 1; }
  r=(CLAMP_O_BPS=100000 RELAYER_STALE_INTERNAL=2 INTERNAL_CAP=0.01 "MARK3=e;${mk:6}" MARK3_INT=1)
  [[ $mk[6] == q ]] && r+=(MARK3_RATCHET=b)
  [[ $mk[6] == r ]] && r+=(MARK3_RATCHET=1)
  print -r -- $r
}
