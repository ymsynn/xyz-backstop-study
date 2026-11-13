#!/bin/zsh
# Vault unwind policies on the 3 crashes. Packages: today (HL mark, today's rules) and p4d_rb2 (P4d mark + restore-to-IM).
# Policies (POLS): clip (0.5% of inventory per update, fitted on the real vault), c2 / c5 (2% / 5%), fair (clip + every
# order at or better than the external price), fair0 (only the fair sweep). Logs: data/scen/vault/log_{COIN}_{pkg}_{pol}.csv
cd ${REPO:-$PWD}
V=data/scen/vault; mkdir -p $V
pol_env() { case $1 in clip) ;; c2) echo VAULT_FRAC=0.02;; c5) echo VAULT_FRAC=0.05;; fair) echo VAULT_FAIR=1;; fair0) echo VAULT_FAIR=1 VAULT_FRAC=0;; esac }
for spec in "GOOGL data/prep_GOOGL_1028 20 1793217600000" "INTC data/prep_INTC_1029 10 1793304000000" "AMZN data/prep_AMZN_1029 20 1793304000000"; do
  a=(${=spec}); c=$a[1] D=$a[2] L=$a[3] T=$a[4]
  for pkg in ${=PKGS:-today p4d_rb2}; do
    if [[ $pkg == today ]]; then X=(); A=(); else X=(MARK=own_et OWN_SELF=1 OWN_H_S=30 OWN_GATE=2 OWN_N=6000 OWN_HOLD_S=150 OWN_HOLD_STEP=1 OWN_FROM_MS=$T); A=(liq_restore=2 restore_big=1); fi
    for p in ${=POLS:-clip c2 c5 fair fair0}; do
      env MATCH=engine TRIGGERS=simulate SILENT=1 MARGIN=1 ENDO=0 MARK_SOURCE=simulate RELAYER_RESID_IN=$D/relayer_resid_endo0_policy.txt $X ${=$(pol_env $p)} \
        VAULT_LOG=$V/log_${c}_${pkg}_$p.csv SIM_TK_OUT=$V/tk_${c}_${pkg}_$p.csv ORC_OUT=$V/orc_${c}.csv \
        tools/memguard.sh 6000 engine/target/release/engine sim $D $L $A 2>&1 | grep -E "^VAULT|fair sweep|takeover notional|memguard: peak" | sed "s/^/$c $pkg $p: /"
    done
  done
done
echo VAULT RUNS DONE
