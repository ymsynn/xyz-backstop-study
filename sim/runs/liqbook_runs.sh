#!/bin/zsh
# Liquidation replays of a market-day: every liquidation round, takeover and mark input, under a named set of rules.
#   today                    today's mark and today's sizing (20% per round above $100k, 30 s apart)
#   rim                      today's mark with the cut-back to initial margin (the Hyperliquid change alone)
#   lead3<k|q|r><seconds>    the three-vote mark (sim/pkgm_env.zsh) with the cut-back; lead3q1800 is the proposal
#   lead3...s20              the same mark with today's sizing (the relayer changes alone)
# Isolated-only (noCross) markets: the backstop is auto-deleveraging (engine backstop=adl) for every design; a design
# ending in x (todayx, lead3q1800x) keeps the vault backstop instead (the market with cross margin enabled).
# Usage: [DES="today rim lead3q1800s20 lead3q1800"] [EV="COIN/MMDD/MAXLEV ..."] [ADL=1] zsh sim/runs/liqbook_runs.sh
#        -> $S (default data/scen/liqbook)/{liq,orc,tk,rd,log}_{COIN}_{DAY}_{des}.csv
cd "${0:A:h}/../.."
source $PWD/sim/pkgm_env.zsh
S=${S:-$PWD/data/scen/liqbook}; mkdir -p $S
# isolated-only (noCross) coins get the ADL backstop automatically (xyzmeta margin mode); PREP_SUFFIX / NAME_SUFFIX: a
# variant prep dir (data/prep_{COIN}_{DAY}{PREP_SUFFIX}) and output tag (contagion pass: _p2)
nox() { ${PY:-python3} -c "import json,sys; u={x['name']:x.get('marginMode') for x in json.load(open('data/xyzmeta.json'))[0]['universe']}; sys.exit(0 if u.get('xyz:$1') in ('noCross','strictIsolated') else 1)"; }
run() { # coin day maxlev design
  local c=$1 day=$2 L=$3 des=$4 D=data/prep_$1_$2${PREP_SUFFIX:-} X=() A=()
  local n=${c}_${day}_$des${NAME_SUFFIX:-}
  # an x design on an isolated-only coin: the vault backstops it, but its positions stay isolated (iso_only)
  [[ $(nox $c && echo 1) == 1 && $des == *x ]] && A+=(iso_only=1)
  [[ ( -n ${ADL:-} || $(nox $c && echo 1) == 1 ) && $des != *x ]] && A+=(backstop=adl); des=${des%x}
  # lead3<k|q|r><seconds>: the three-vote mark (sim/pkgm_env.zsh) with the cut-back; ...s20: the same mark with today's
  # sizing (20% per round, 30 s apart); rim: today's mark with the cut-back
  local s20=0; [[ $des == lead3*s20 ]] && { s20=1; des=${des%s20}; }
  [[ $des == lead3* ]] && X=(${=$(pkgm_extra pkgm3${des#lead3})})
  [[ $des != today && $des != rim && $des != lead3* ]] && { print -u2 "liqbook_runs: unknown design $des"; return 1; }
  [[ $s20 == 0 && ( $des == rim || $des == lead3* ) ]] && A+=(liq_restore=2 restore_big=1)
  env MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_IN=$D/relayer_resid_endo0_policy.txt $X \
      LIQ_ROUNDS_OUT=$S/liq_$n.csv ORC_OUT=$S/orc_$n.csv SIM_TK_OUT=$S/tk_$n.csv ROUNDS_OUT=$S/rd_$n.csv VAULT_LOG=$S/log_$n.csv \
      tools/memguard.sh 12 ${ENGINE:-engine/target/release/engine} sim $D $L $A 2>&1 | grep -E "takeover notional|BAD DEBT|memguard: peak" | sed "s/^/$n: /"
}
for ev in ${=EV:-GOOGL/1028/20 INTC/1029/10 AMZN/1029/20 GOOGL/1020/20 INTC/1020/10 AMZN/1020/20 GOOGL/1021/20 INTC/1021/10 AMZN/1021/20}; do
  IFS=/ read c day L <<< "$ev"
  for des in ${=DES:-today rim lead3q1800s20 lead3q1800}; do run $c $day $L $des; done
done
echo LIQBOOK DONE
