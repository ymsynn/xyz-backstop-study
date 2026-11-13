#!/bin/zsh
# Local copy of ec2/oos_job.sh's REVAL step: internal-session windows + relayer residual v2 for a prep from S3, validation,
# then the out-of-sample runs (today, previous candidate, three-vote mark). Usage: zsh reval_oos.sh COIN DAY MAXLEV
cd ${REPO:-$PWD}; T=$PWD/data/scen/tests_1110f; PY=python3
C=$1; DAY=$2; L=$3; D=data/prep_${C}_$DAY
if [[ ! -f $D/relayer_resid_v1.txt ]]; then
  $PY sim/closed_windows.py --internal --prep $D > $D/internal_windows.txt
  B=(MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate)
  { echo "== internal windows: $(cat $D/internal_windows.txt)"
    env "${B[@]}" RELAYER_RESID_OUT=$D/relayer_resid_v2.txt engine/target/release/engine sim $D $L 2>&1 | grep -E "relayer|internal"
    echo "== validation v2 (real parameters, residual v2 in)"
    env "${B[@]}" RELAYER_RESID_IN=$D/relayer_resid_v2.txt engine/target/release/engine sim $D $L 2>&1 | grep -E "relayer|mark|takeovers|liquidat|rounds|BAD DEBT|END-OF-DAY|internal"
  } > $T/reval_${C}_$DAY.log 2>&1
  [[ -s $D/relayer_resid_v2.txt ]] || { echo "$C $DAY: no residual v2"; exit 1; }
  cp $D/relayer_resid_endo0_policy.txt $D/relayer_resid_v1.txt; cp $D/relayer_resid_v2.txt $D/relayer_resid_endo0_policy.txt
fi
PY=$PY PKS="today pkgmint pkgm3e1800" zsh $T/oos_runs2.sh $DAY $C $L > $T/oos2/stdout_${C}_$DAY.txt 2>&1
echo "$C $DAY done"
