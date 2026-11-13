# Extra engine settings for the core-package family, shared by every run script.
#   pkgm                 core package (package_k without the fair sweep)
#   pkgmc                + the oracle follows E at once only as far as xyz's book already is, else c per update
#   pkgm050|100|200      + closed-market oracle input cap 0.5 / 1 / 2 %          (INTERNAL_CAP)
#   pkgmd<g>[c|s|v|n]    + divergence holds at g/10000 (250 = 2.5%)             (OWN_DIVERGE)
#                          then a held centre steps toward E: (none) every 150 s; c|s only while xyz has no trade in the
#                          window (count); v only while xyz's volume in the window is below the day's average; n never
pkgm_extra() {
  local mk=$1 r=() g suf
  case $mk in
    pkgm) ;;
    pkgmc) r+=(ORACLE_CORROB=1);;   # corroborated speed: follow E at once only as far as xyz's book is
    pkgmint) r+=(RELAYER_STALE_INTERNAL=2 INTERNAL_CAP=0.01 OWN_NO_FROZEN=1);;   # B: a frozen E is priced like a closure
    # the three-vote mark on the lead's other rules: pkgm3aNN anchor pace NN bp per update (pkgm3a50 = 0.5% per
    # update, Hyperliquid's own limit; pkgm3a0 frozen), pkgm3eSSS an average with time constant SSS seconds (MARK3)
    pkgm3a*) r+=(RELAYER_STALE_INTERNAL=2 INTERNAL_CAP=0.01 OWN_NO_FROZEN=1 MARK3="a;$(( ${mk#pkgm3a} / 10000.0 ))");;
    pkgm3e*) r+=(RELAYER_STALE_INTERNAL=2 INTERNAL_CAP=0.01 OWN_NO_FROZEN=1 MARK3="e;${mk#pkgm3e}");;
    # pkgm3nSSS: the same without the unchanged-feed rule. An unchanged E is still a vote (overnight it is unchanged on
    # three updates out of four, and a walked-then-held feed looks "not live"): the anchor is kept whenever the venue is
    # open; the internal oracle runs in scheduled closures only
    pkgm3n*) r+=(INTERNAL_CAP=0.01 OWN_NO_FROZEN=1 MARK3="e;${mk#pkgm3n}");;
    # pkgm3kSSS: one formula in every regime. Feed not live (closure, or E unchanged for two updates): its vote is the
    # internal oracle instead of E, and the anchor keeps running toward that vote (never restarted)
    pkgm3k*) r+=(RELAYER_STALE_INTERNAL=2 INTERNAL_CAP=0.01 OWN_NO_FROZEN=1 MARK3="e;${mk#pkgm3k}" MARK3_INT=1);;
    # pkgm3rSSS: pkgm3k + the anchor never lags the mark: after its step it is brought inside [vote, previous mark]
    # pkgm3q1800 = THE CHAMPION, formula FROZEN 2026-11-11 (sim/tests_1110/RESULTS_7, RESULTS_12): three votes, one formula,
    # book-aware ratchet, tau 30 min, kappa 1%, internal oracle unrounded; engine default ONE_SIDED=quote. A change reopens the design.
    # ratchet variants (30 min anchor): pkgm3q book-aware (skipped when the book decided the previous mark),
    # pkgm3x / pkgm3y the anchor follows only what the mark has held for 30 s / 150 s
    # anchor band (reopens the frozen formula; tests of 2026-11-11): both inputs within a band of the plain 30 min average
    # pkgm3u = no ratchet + band 1/maxLev | pkgm3v = book-aware ratchet + band 1/maxLev | pkgm3s = book-aware + half band
    pkgm3u*) r+=(RELAYER_STALE_INTERNAL=2 INTERNAL_CAP=0.01 OWN_NO_FROZEN=1 MARK3="e;${mk#pkgm3u}" MARK3_INT=1 MARK3_BAND=d);;
    pkgm3v*) r+=(RELAYER_STALE_INTERNAL=2 INTERNAL_CAP=0.01 OWN_NO_FROZEN=1 MARK3="e;${mk#pkgm3v}" MARK3_INT=1 MARK3_RATCHET=b MARK3_BAND=d);;
    pkgm3s*) r+=(RELAYER_STALE_INTERNAL=2 INTERNAL_CAP=0.01 OWN_NO_FROZEN=1 MARK3="e;${mk#pkgm3s}" MARK3_INT=1 MARK3_RATCHET=b MARK3_BAND=h);;
    pkgm3q*) r+=(RELAYER_STALE_INTERNAL=2 INTERNAL_CAP=0.01 OWN_NO_FROZEN=1 MARK3="e;${mk#pkgm3q}" MARK3_INT=1 MARK3_RATCHET=b);;
    pkgm3x*) r+=(RELAYER_STALE_INTERNAL=2 INTERNAL_CAP=0.01 OWN_NO_FROZEN=1 MARK3="e;${mk#pkgm3x}" MARK3_INT=1 MARK3_RATCHET=w30);;
    pkgm3y*) r+=(RELAYER_STALE_INTERNAL=2 INTERNAL_CAP=0.01 OWN_NO_FROZEN=1 MARK3="e;${mk#pkgm3y}" MARK3_INT=1 MARK3_RATCHET=w150);;
    pkgm3r*) r+=(RELAYER_STALE_INTERNAL=2 INTERNAL_CAP=0.01 OWN_NO_FROZEN=1 MARK3="e;${mk#pkgm3r}" MARK3_INT=1 MARK3_RATCHET=1);;
    pkgmintc) r+=(RELAYER_STALE_INTERNAL=2 INTERNAL_CAP=0.01 OWN_NO_FROZEN=1 ORACLE_CORROB=1);;   # the lead + corroborated speed
    # the lead + the persistence rule on E: pkgmintpBBBwSSS = band BBB bp, window SSS seconds (EXT_PERSIST)
    pkgmintp*) g=${mk#pkgmintp}; r+=(RELAYER_STALE_INTERNAL=2 INTERNAL_CAP=0.01 OWN_NO_FROZEN=1 EXT_PERSIST="$(( ${g%w*} / 10000.0 ));${g#*w}");;
    pkgmbook) r+=(OWN_N_SELF=1);;   # C: the hold's book checks at the self-calibrated depth V
    pkgm[0-9]*) r+=(INTERNAL_CAP=$(( ${mk#pkgm} / 10000.0 )));;
    pkgmd*) g=${mk#pkgmd}; suf=${g//[0-9]/}; g=${g//[a-z]/}; r+=(OWN_DIVERGE=$(( g / 10000.0 )))
            case $suf in c|s) r+=(OWN_STEP_STALE=1);; v) r+=(OWN_STEP_STALE=2);; n) r+=(OWN_STEP_STALE=3);; esac;;
  esac
  # the three-vote mark stands alone: the earlier candidate's hold on an impossible jump of the external price is off
  # (decided 2026-11-12; until then the replays ran it underneath, and it fired on SK Hynix on July 27)
  [[ $mk == pkgm3* ]] && r+=(MARK3_PURE=1)
  print -r -- ${r[@]}
}
