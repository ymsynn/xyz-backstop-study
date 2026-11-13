#!/bin/bash
# Out-of-sample job, run on one spot instance (user-data of ec2/days_launch.sh): for each day, extract the xyz command
# stream (resuming from parts already in S3), reduce it to tables, pull the hydromancer / node inputs, run the full
# prep + validation pipeline per coin (sim/pipe_day.sh) and the replays (sim/runs/liqbook_runs.sh, or sim/final/oos_runs.sh without DAYS_DES); upload logs, results
# and preps to s3://$BUCKET/backstop/oos/. Every stage leaves a done-marker in S3, so a relaunch resumes.
# Env: BUCKET REGION DAYS (space-separated specs DAY@NEXT@SNAP@MIN_H@COIN/ASSET/MAXLEV,...; @ because SNAP has colons)
set -uxo pipefail
exec > >(tee -a /var/log/oos.log) 2>&1
S3=s3://$BUCKET/backstop/oos; RP=(--request-payer requester --region $REGION --only-show-errors); RL=(--request-payer requester --region $REGION)
beat() { echo "$(date -u) ${IID0:-} $*" > /tmp/hb; aws s3 cp /tmp/hb $S3/HEARTBEAT.txt --region $REGION --only-show-errors; aws s3 cp /tmp/hb $S3/hb/${IID0:-x}.txt --region $REGION --only-show-errors; }
done_s3() { aws s3 ls $S3/done/$1 --region $REGION >/dev/null 2>&1; }
mark() { echo "$(date -u)" > /tmp/m; aws s3 cp /tmp/m $S3/done/$1 --region $REGION --only-show-errors; }
# each instance keeps its own log and heartbeat (several can run at once)
IID0=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 600" | xargs -I{} curl -s -H "X-aws-ec2-metadata-token: {}" http://169.254.169.254/latest/meta-data/instance-id)
up_log() { aws s3 cp /var/log/oos.log $S3/logs_job/oos_$IID0.log --region $REGION --only-show-errors; aws s3 cp /var/log/oos.log $S3/oos.log --region $REGION --only-show-errors; }
# on any exit, success or failure: upload the log, then terminate this instance (never leave a box running)
finish() { up_log; aws ec2 terminate-instances --region $REGION --instance-ids $IID0 >/dev/null 2>&1 || shutdown -h now; }
trap finish EXIT
# MAX_MIN: hard cap on the job's wall time; the box powers off and terminates whatever state it is in
[ -n "${MAX_MIN:-}" ] && shutdown -h +$MAX_MIN
beat "starting"
# ---- toolchain and code, at the paths the scripts expect
dnf install -y python3 python3-pip python3.12 python3.12-pip lz4 zsh git gcc procps-ng >/dev/null
python3.12 -m venv /root/venv
/root/venv/bin/pip install -q polars==1.41.1 numpy==2.4.6 orjson msgpack==1.1.2 lz4==4.4.5
export PY=/root/venv/bin/python
# the toolchain download has failed before (2026-11-11, network error from Tokyo): retry, and never go on without an engine
for k in 1 2 3 4 5 6; do curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal >/dev/null && [ -x /root/.cargo/bin/cargo ] && /root/.cargo/bin/cargo --version >/dev/null 2>&1 && break; sleep 30; done
source /root/.cargo/env
W=/root/backstop; mkdir -p $W && cd $W
aws s3 cp $S3/code/code.tgz /tmp/code.tgz --region $REGION && tar xzf /tmp/code.tgz
(cd engine && cargo build --release 2>&1 | tail -2)
[ -x engine/target/release/engine ] || { beat "ENGINE BUILD FAILED: stopping before any paid work"; exit 1; }
beat "engine built"
for spec in $DAYS; do
  IFS=@ read DAY NX SNAP MIN_H COINS <<< "$spec"
  YYYY=2026; MM=${DAY:0:2}; DD=${DAY:2:2}; NM=${NX:0:2}; ND=${NX:2:2}
  ASSETS=$(echo $COINS | tr ',' '\n' | cut -d/ -f2 | paste -sd,)
  # SNAP=auto: every replica_cmds snapshot folder that holds this day, oldest first. The node archive starts a new folder
  # at each of its snapshots, so a day can be split over two (2026-11-05: 00:00-09:49 in the 10-31 folder, the rest in the
  # 11-05 folder; taking only the latest lost the first ten hours). MIN_H=auto: the day's hydromancer snapshot block
  SNAPS="$SNAP"
  if [ "$SNAP" = auto ]; then
    aws s3 ls s3://hl-mainnet-node-data/replica_cmds/ "${RL[@]}" > snaps.txt 2>&1
    aws s3 cp snaps.txt $S3/logs_job/snaps_$IID0.txt --region $REGION --only-show-errors
    SNAPS=""
    for s in $(awk '/PRE/ {print $2}' snaps.txt | tr -d / | sort); do
      n=$(aws s3 ls "s3://hl-mainnet-node-data/replica_cmds/$s/$YYYY$MM$DD/" "${RL[@]}" 2>/dev/null | grep -c lz4)
      [ "$n" -gt 0 ] && SNAPS="$SNAPS $s"
    done
    beat "snapshot folders for $DAY:$SNAPS ($(grep -c PRE snaps.txt) folders listed)"
    [ -n "$SNAPS" ] || { beat "no snapshot folder holds $DAY"; [ -n "${SKIP_BAD_DAYS:-}" ] && { echo "$DAY" >> skipped_days.txt; aws s3 cp skipped_days.txt $S3/skipped_days_$IID0.txt --region $REGION --only-show-errors; continue; }; exit 1; }
  fi
  if [ "$MIN_H" = auto ]; then
    B0=$(aws s3 ls s3://hydromancer-reservoir/by_dex/xyz/snapshots/perp/date=$YYYY-$MM-$DD/ "${RL[@]}" | awk '{print $4}' | grep parquet | sort | head -1 | cut -d_ -f1)
    MIN_H=$(( B0 - B0 % 10000 )); beat "MIN_H for $DAY: $MIN_H (snapshot block $B0)"
  fi
  # ---- 1. extract (parts per stream file, resumable)
  if ! done_s3 extract_$DAY; then
    beat "extract $DAY"
    mkdir -p parts_$DAY; aws s3 sync $S3/parts/$DAY/ parts_$DAY/ --region $REGION --only-show-errors
    : > keys_$DAY.txt   # one line per stream file: folder/file
    for s in $SNAPS; do aws s3 ls "s3://hl-mainnet-node-data/replica_cmds/$s/$YYYY$MM$DD/" "${RL[@]}" | awk -v s=$s '{print s "/" $4}' | grep lz4 >> keys_$DAY.txt; done
    [ -z "$(cut -d/ -f2 keys_$DAY.txt | sort | uniq -d)" ] || { beat "extract $DAY: the same file name in two snapshot folders"; [ -n "${SKIP_BAD_DAYS:-}" ] && { echo "$DAY" >> skipped_days.txt; aws s3 cp skipped_days.txt $S3/skipped_days_$IID0.txt --region $REGION --only-show-errors; continue; }; exit 1; }
    cat keys_$DAY.txt | xargs -P $(nproc) -I '{}' bash -c 'set -o pipefail; k="{}"; s="${k%%/*}"; f="${k##*/}"; o="parts_'$DAY'/${f%.lz4}.jsonl.gz"; [ -s "$o" ] && [ $(stat -c%s "$o") -gt 200 ] && exit 0;
      aws s3 cp "s3://hl-mainnet-node-data/replica_cmds/$s/'$YYYY$MM$DD'/$f" - --request-payer requester --region '$REGION' 2>>aws_err_'$DAY'.txt | lz4 -dc 2>>aws_err_'$DAY'.txt \
      | '$PY' ec2/extract.py '$MIN_H' "$o" '$ASSETS' && [ $(stat -c%s "$o") -gt 200 ] && aws s3 cp "$o" "'$S3'/parts/'$DAY'/" --region '$REGION' --only-show-errors || echo "FAIL $k" >> fails_'$DAY'.txt'
    # a part of 200 bytes or less holds no block at all: a failed read, not an empty stream file (every file has its block rows)
    [ -s aws_err_$DAY.txt ] && { head -c 4000 aws_err_$DAY.txt > aws_err_head.txt; aws s3 cp aws_err_head.txt $S3/logs_job/aws_err_${DAY}_$IID0.txt --region $REGION --only-show-errors; }
    [ -f fails_$DAY.txt ] && { aws s3 cp fails_$DAY.txt $S3/fails_$DAY.txt --region $REGION; beat "extract $DAY had failures"; [ -n "${SKIP_BAD_DAYS:-}" ] && { echo "$DAY" >> skipped_days.txt; aws s3 cp skipped_days.txt $S3/skipped_days_$IID0.txt --region $REGION --only-show-errors; continue; }; exit 1; }
    # FILL_HOLES="first-last ...": blocks that no replica_cmds folder holds (the archive's stream stops a few minutes
    # before its next snapshot folder starts), taken from explorer_blocks instead: the same actions in executed order,
    # without the exchange's responses, which ec2/extract_explorer.py infers (checked by sim/prep/explorer_check.py)
    NH=0
    for hole in ${FILL_HOLES:-}; do
      lo=${hole%-*}; hi=${hole#*-}; mkdir -p eb_$DAY; NH=$((NH+1))
      for n in $(python3 -c "print(' '.join(str(n) for n in range(-(-$lo//100)*100, -(-$hi//100)*100+1, 100)))"); do
        d1=$(( (n-1)/100000000*100000000 )); d2=$(( (n-1)/100000*100000 ))
        [ -s eb_$DAY/$n.rmp.lz4 ] || aws s3 cp s3://hl-mainnet-node-data/explorer_blocks/$d1/$d2/$n.rmp.lz4 eb_$DAY/ "${RP[@]}" || { beat "extract $DAY: explorer block file $n missing"; exit 1; }
      done
      $PY ec2/extract_explorer.py $lo $hi parts_$DAY/$lo.jsonl.gz $ASSETS eb_$DAY/*.rmp.lz4 2> hole_$lo.txt || { beat "extract $DAY: hole $hole failed: $(tail -1 hole_$lo.txt)"; exit 1; }
      aws s3 cp parts_$DAY/$lo.jsonl.gz $S3/parts/$DAY/ --region $REGION --only-show-errors
      beat "hole $hole of $DAY filled from explorer_blocks: $(cat hole_$lo.txt)"
    done
    NK=$(( $(wc -l < keys_$DAY.txt) + NH )); NP=$(ls parts_$DAY | wc -l)
    [ "$NK" -gt 0 ] && [ "$NP" -eq "$NK" ] || { beat "extract $DAY incomplete: $NP parts of $NK files"; [ -n "${SKIP_BAD_DAYS:-}" ] && { echo "$DAY" >> skipped_days.txt; aws s3 cp skipped_days.txt $S3/skipped_days_$IID0.txt --region $REGION --only-show-errors; continue; }; exit 1; }
    mark extract_$DAY
  fi
  # ---- 2. reduce to tables
  if ! done_s3 tables_$DAY; then
    beat "reduce $DAY"
    mkdir -p parts_$DAY; aws s3 sync $S3/parts/$DAY/ parts_$DAY/ --region $REGION --only-show-errors
    mkdir -p data/extract$DAY/tables
    $PY ec2/reduce.py parts_$DAY data/extract$DAY/tables 2>&1 | tail -3
    $PY -c "import polars as pl,sys; d='data/extract$DAY/tables'; sys.exit(0 if pl.scan_parquet(d+'/orders.parquet').select(pl.len()).collect().item()>0 and pl.scan_parquet(d+'/oracle.parquet').select(pl.len()).collect().item()>0 else 1)" || { beat "reduce $DAY produced no rows"; [ -n "${SKIP_BAD_DAYS:-}" ] && { echo "$DAY" >> skipped_days.txt; aws s3 cp skipped_days.txt $S3/skipped_days_$IID0.txt --region $REGION --only-show-errors; continue; }; exit 1; }
    aws s3 sync data/extract$DAY/tables/ $S3/tables/$DAY/ --region $REGION --only-show-errors
    mark tables_$DAY
  else
    aws s3 sync $S3/tables/$DAY/ data/extract$DAY/tables/ --region $REGION --only-show-errors
  fi
  # coverage: the tables must start at the snapshot block and have no hole (a missing stream file or folder)
  $PY - <<EOF || { beat "tables $DAY do not cover the day from the snapshot block $MIN_H: $(cat cover_$DAY.txt)"; [ -n "${SKIP_BAD_DAYS:-}" ] && { echo "$DAY" >> skipped_days.txt; aws s3 cp skipped_days.txt $S3/skipped_days_$IID0.txt --region $REGION --only-show-errors; continue; }; exit 1; }
import polars as pl, sys
b = pl.read_parquet("data/extract$DAY/tables/blocks.parquet", columns=["h", "t"]).sort("h")
# KNOWN_GAPS="last-first ...": holes of the node archive itself, declared by hand (2026-11-05: 1209897579-1209901625, the
# archive's stream stops at 09:45:08 UTC and its next snapshot folder starts at 09:49:50); any other hole fails the job
known = {tuple(int(x) for x in g.split("-")) for g in "${KNOWN_GAPS:-}".split()}
g = b.with_columns(prev=pl.col("h").shift(1), dh=pl.col("h").diff()).filter(pl.col("dh") > 100)
holes = [(int(r["prev"]), int(r["h"])) for r in g.iter_rows(named=True)]
bad = [x for x in holes if x not in known]; h0 = int(b["h"].min())
msg = f"first block {h0} ({b['t'][0]}), last {int(b['h'].max())} ({b['t'][-1]}), holes {holes or 'none'}" + (f", UNDECLARED {bad}" if bad else "")
open("cover_$DAY.txt", "w").write(msg); print("coverage $DAY:", msg)
sys.exit(0 if h0 <= $MIN_H + 100 and not bad else 1)
EOF
  beat "coverage $DAY ok: $(cat cover_$DAY.txt)"
  rm -rf parts_$DAY
  # ---- 3. inputs (hydromancer, node misc), the day and the next day
  beat "pull $DAY"
  H=s3://hydromancer-reservoir/by_dex/xyz; G=s3://hydromancer-reservoir/global
  Q=()   # all downloads at once (independent prefixes)
  for pair in "$MM $DD" "$NM $ND"; do
    read m d <<< "$pair"
    aws s3 cp $H/fills/perp/all/date=$YYYY-$m-$d/fills.parquet data/xyzdata/all$m$d.parquet "${RP[@]}" & Q+=($!)
    aws s3 sync $H/snapshots/perp/date=$YYYY-$m-$d/ data/xyzdata/snap$m$d/ "${RP[@]}" & Q+=($!)
    aws s3 sync $G/snapshots/account_values/date=$YYYY-$m-$d/ data/global$m$d/account_values/ "${RP[@]}" & Q+=($!)
    aws s3 sync $G/snapshots/perp/all/date=$YYYY-$m-$d/ data/global$m$d/perp_all/ "${RP[@]}" & Q+=($!)
    aws s3 sync $G/snapshots/spot/date=$YYYY-$m-$d/ data/global$m$d/spot/ "${RP[@]}" & Q+=($!)
  done
  aws s3 sync $H/fills/perp/liquidations/date=$YYYY-$MM-$DD/ data/xyzdata/liquidations/date=$YYYY-$MM-$DD/ "${RP[@]}" & Q+=($!)
  aws s3 sync s3://hl-mainnet-node-data/misc_events_by_block/hourly/$YYYY$MM$DD/ data/nodedata/misc$DAY/ --request-payer requester --only-show-errors & Q+=($!)
  mkdir -p data/global$DAY/fills_raw; aws s3 sync $G/fills/raw/date=$YYYY-$MM-$DD/ data/global$DAY/fills_raw/ "${RP[@]}" & Q+=($!)
  for cs in $(echo $COINS | tr ',' ' '); do IFS=/ read C A L <<< "$cs"
    aws s3 cp $H/orderbook/1m/perps/date=$YYYY-$MM-$DD/$C.parquet data/xyzdata/ob1m_${C}_$DAY.parquet "${RP[@]}" & Q+=($!); done
  wait "${Q[@]}"
  # the day's orders / cancels split by coin once (they are in time order, so each coin's filtered scans read the whole
  # day otherwise); each coin's pipeline then reads data/extract$DAY/bycoin/$C
  beat "split $DAY"
  $PY -I sim/prep/split_tables.py data/extract$DAY/tables data/extract$DAY/bycoin $(echo $COINS | tr ',' '\n' | cut -d/ -f1,2 | paste -sd,) || { beat "split $DAY failed"; [ -n "${SKIP_BAD_DAYS:-}" ] && { echo "$DAY" >> skipped_days.txt; aws s3 cp skipped_days.txt $S3/skipped_days_$IID0.txt --region $REGION --only-show-errors; continue; }; exit 1; }
  # ---- 4. per coin: prep + validation pipeline, then the replays. PAR coins at once (each step is single-core,
  # peak ~11 GB on the largest 11-05 coins); POLARS_MAX_THREADS keeps them from fighting over cores
  TG=${RUN_TAG:+${RUN_TAG}_}; JD=joint${RUN_TAG:+_$RUN_TAG}; PD=preps${RUN_TAG:+_$RUN_TAG}
  PAR=${PAR:-1}; export POLARS_MAX_THREADS=${POLARS_MAX_THREADS:-$(( $(nproc) / PAR > 0 ? $(nproc) / PAR : 1 ))}
  live() { local n=0 p; for p in "${P[@]}"; do kill -0 $p 2>/dev/null && n=$((n+1)); done; echo $n; }
  throttle() { while [ "$(live)" -ge "$PAR" ]; do sleep 5; done; }
  one_coin() {
    local cs=$1 C A L DS; IFS=/ read C A L <<< "$cs"
    # ONLY="COIN ...": a trial on a few coins of the list (the extract and the tables still cover every coin of COINS)
    if [ -n "${ONLY:-}" ]; then case " $ONLY " in *" $C "*) ;; *) return 0;; esac; fi
    done_s3 ${TG}coin_${C}_$DAY && return 0
    beat "pipe $C $DAY"
    E_DIR=data/extract$DAY/bycoin/$C VALIDATE=0 zsh sim/pipe_day.sh $DAY $NX $C $A $L > pipe_${C}_$DAY.log 2>&1
    aws s3 cp pipe_${C}_$DAY.log $S3/logs/ --region $REGION --only-show-errors
    grep -q "PIPE DONE" pipe_${C}_$DAY.log && [ -s data/prep_${C}_$DAY/relayer_resid_endo0_policy.txt ] || { beat "pipe $C $DAY failed"; return 0; }
    # RUN_TAG: is the prep just built byte-identical to the one stored in REF_PREPS (default preps_final, the paper's
    # market-days)? Reproducibility across machines and code versions
    if [ -n "${RUN_TAG:-}" ] && aws s3 cp $S3/${REF_PREPS:-preps_final}/prep_${C}_$DAY.tgz /tmp/old_${C}_$DAY.tgz --region $REGION --only-show-errors 2>/dev/null; then
      mkdir -p /tmp/old_${C}_$DAY && tar xzf /tmp/old_${C}_$DAY.tgz -C /tmp/old_${C}_$DAY && rm -f /tmp/old_${C}_$DAY.tgz
      ( cd data/prep_${C}_$DAY && find . -type f | sort | xargs md5sum ) > /tmp/new_${C}_$DAY.md5
      ( cd /tmp/old_${C}_$DAY/prep_${C}_$DAY && find . -type f | sort | xargs md5sum ) > /tmp/oldh_${C}_$DAY.md5
      { echo "files new $(wc -l < /tmp/new_${C}_$DAY.md5) stored $(wc -l < /tmp/oldh_${C}_$DAY.md5), differing lines $(diff /tmp/new_${C}_$DAY.md5 /tmp/oldh_${C}_$DAY.md5 | grep -c '^[<>]')"; diff /tmp/new_${C}_$DAY.md5 /tmp/oldh_${C}_$DAY.md5; } > prepcmp_${C}_$DAY.txt
      aws s3 cp prepcmp_${C}_$DAY.txt $S3/$JD/ --region $REGION --only-show-errors; rm -rf /tmp/old_${C}_$DAY
    fi
    tar czf prep_${C}_$DAY.tgz -C data prep_${C}_$DAY && aws s3 cp prep_${C}_$DAY.tgz $S3/$PD/ --region $REGION --only-show-errors && rm -f prep_${C}_$DAY.tgz
    beat "runs $C $DAY"
    if [ -n "${DAYS_DES:-}" ]; then
      # joint-day study: the liquidation-size designs per coin (noCross coins with the ADL backstop), x designs for X_COINS
      DS="$DAYS_DES"; case " ${X_COINS:-} " in *" $C "*) for d in $DAYS_DES; do DS="$DS ${d}x"; done;; esac   # every design, with cross margin enabled
      EV="$C/$DAY/$L" S=$PWD/data/scen/joint DES="$DS" zsh sim/runs/liqbook_runs.sh > joint_${C}_$DAY.log 2>&1
      aws s3 sync data/scen/joint/ $S3/$JD/ --region $REGION --only-show-errors --exclude '*' --include "*_${C}_${DAY}_*"
      aws s3 cp joint_${C}_$DAY.log $S3/$JD/ --region $REGION --only-show-errors
      [ -s data/scen/joint/orc_${C}_${DAY}_today.csv ] && mark ${TG}coin_${C}_$DAY || beat "joint runs $C $DAY failed"
    else
      FINAL_OUT=$PWD/data/scen PKS="today pkgm3q1800" zsh sim/final/oos_runs.sh $DAY $C $L > /dev/null 2>&1
      aws s3 sync data/scen/oos/ $S3/results/ --region $REGION --only-show-errors
      [ -s data/scen/oos/tk_${C}_${DAY}_pkgm3q1800.csv ] && mark ${TG}coin_${C}_$DAY || beat "runs $C $DAY failed"
    fi
  }
  # DETCHECK="COIN/ASSET/MAXLEV ...": the reproducibility check on this machine, on these coins of the day (three builds
  # each with 1, 2 and 8 polars threads, every file compared), next to the real runs. The verdicts and hashes go to S3,
  # and so do the files of any difference (builds t1 and t8), so a failure can be read after the box is gone
  DC=""
  if [ -n "${DETCHECK:-}" ]; then
    ( v=""
      for dc in $DETCHECK; do
        IFS=/ read C A L <<< "$dc"; O=/root/detcheck_${C}_$DAY
        zsh tools/determinism_check.sh $DAY $NX $C $A $L $O "1 2 8" > detcheck_${C}_$DAY.log 2>&1
        aws s3 cp detcheck_${C}_$DAY.log $S3/$JD/ --region $REGION --only-show-errors
        for t in 1 2 8; do aws s3 cp $O/hash_t$t.txt $S3/$JD/detcheck_${C}_${DAY}_hash_t$t.txt --region $REGION --only-show-errors; done
        for f in $(grep -E '^ +[<>] ' detcheck_${C}_$DAY.log | awk '{print $2}' | sort -u); do
          for t in 1 8; do aws s3 cp $O/t$t/$f $S3/detcheck_diff/${C}_$DAY/t$t/$f --region $REGION --only-show-errors; done; done
        v="$v $C:$(tail -1 detcheck_${C}_$DAY.log | awk '{print $2}')"
        rm -rf $O
      done
      echo "$v" > detcheck_$DAY.txt; aws s3 cp detcheck_$DAY.txt $S3/$JD/ --region $REGION --only-show-errors ) & DC=$!
  fi
  P=()
  for cs in $(echo $COINS | tr ',' ' '); do throttle; one_coin "$cs" & P+=($!); sleep 2; done
  [ ${#P[@]} -gt 0 ] && wait "${P[@]}"
  if [ -n "${CONTAGION:-}" ]; then
    # second pass: every cross account sees the other coins' simulated relayer inputs (first pass, same design) instead
    # of the real ones; crossacc rebuilds its outside collateral, then the design is rerun (outputs tagged _p2). Coins done
    # by an earlier instance: their first-pass outputs and preps come back from S3
    beat "contagion $DAY"
    aws s3 sync $S3/$JD/ data/scen/joint/ --region $REGION --only-show-errors --exclude '*' --include "orc_*_${DAY}_*"
    for des in ${DAYS_DES:-today lead}; do
      $PY sim/prep/orc_merge.py data/extract$DAY/tables/oracle.parquet data/scen/joint $DAY $des data/extract$DAY/tables/oracle_$des.parquet >> joint_$DAY.log 2>&1
    done
    one_p2() {
      local cs=$1 des=$2 C A L D; IFS=/ read C A L <<< "$cs"; D=data/prep_${C}_$DAY
      done_s3 ${TG}p2_${C}_${DAY}_$des && return 0
      # always under the lock: the other design's job may be mid-untar of the same prep
      (flock 9; [ -f $D/.ok ] || [ -d $D -a ! -f /tmp/fetch_$C ] || { touch /tmp/fetch_$C; aws s3 cp $S3/$PD/prep_${C}_$DAY.tgz /tmp/prep_${C}_$DAY.tgz --region $REGION --only-show-errors && tar xzf /tmp/prep_${C}_$DAY.tgz -C data && rm -f /tmp/prep_${C}_$DAY.tgz; }; [ -d $D ] && touch $D/.ok) 9>/tmp/lock_$C
      [ -d $D ] || { beat "no prep $C (contagion)"; return 0; }
      rm -rf ${D}_p2$des; cp -r $D ${D}_p2$des
      $PY -I sim/prep/crossacc.py ${D}_p2$des data/global$DAY data/nodedata/misc$DAY data/xyzmeta.json xyz:$C data/global$NX data/extract$DAY/tables/oracle_$des.parquet > p2_${C}_${des}.log 2>&1
      EV="$C/$DAY/$L" S=$PWD/data/scen/joint DES="$des" PREP_SUFFIX=_p2$des NAME_SUFFIX=_p2 zsh sim/runs/liqbook_runs.sh >> p2_${C}_${des}.log 2>&1
      rm -rf ${D}_p2$des
      aws s3 sync data/scen/joint/ $S3/$JD/ --region $REGION --only-show-errors --exclude '*' --include "*_${C}_${DAY}_${des}_p2.csv"
      aws s3 cp p2_${C}_${des}.log $S3/$JD/ --region $REGION --only-show-errors
      [ -s data/scen/joint/orc_${C}_${DAY}_${des}_p2.csv ] && mark ${TG}p2_${C}_${DAY}_$des || beat "contagion $C $des failed"
    }
    P=()
    for des in ${DAYS_DES:-today lead}; do for cs in $(echo $COINS | tr ',' ' '); do throttle; one_p2 "$cs" $des & P+=($!); sleep 2; done; done
    [ ${#P[@]} -gt 0 ] && wait "${P[@]}"
    aws s3 cp joint_$DAY.log $S3/$JD/ --region $REGION --only-show-errors
    beat "contagion $DAY done"
  fi
  [ -n "$DC" ] && wait $DC
  rm -rf data/global$DAY data/nodedata/misc$DAY   # keep disk in check between days
done
beat "ALL DONE"
mark all
up_log
TOKEN=$(curl -sX PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 600")
IID=$(curl -sH "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id)
aws ec2 terminate-instances --region $REGION --instance-ids $IID || shutdown -h now
