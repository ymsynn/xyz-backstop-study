#!/bin/zsh
# Reproducibility check of the prep pipeline (sim/pipe_day.sh): the same coin-day is built N times from identical inputs,
# each run with a different polars thread count, and every output file must be byte-identical across runs (prep dir,
# order binding, ledgers, working files).
# Why thread counts: polars returns group_by / unique rows in a per-process order and splits work by thread, so any result
# that leans on an unspecified row order shows up as a difference here.
# Usage: zsh tools/determinism_check.sh DAY NEXT COIN ASSET MAXLEV [OUT_DIR] [THREADS="1 4 8"]
#   e.g. zsh tools/determinism_check.sh 1028 1029 GOOGL 110012 20
# Needs the day's inputs locally (data/extract$DAY/tables, data/xyzdata, data/global$DAY, data/nodedata/misc$DAY).
set -e
cd "${0:A:h}/.."
DAY=$1; NX=$2; C=$3; A=$4; L=$5; OUT=${6:-$(mktemp -d)}; TH=(${=7:-1 4 8})
PY=${PY:-python3}
md5s() { if command -v md5sum > /dev/null; then md5sum "$@"; else md5 -r "$@"; fi; }   # Linux / macOS
mkdir -p $OUT
for t in $TH; do
  R=$OUT/t$t; rm -rf $R; mkdir -p $R
  (
    $PY -I sim/prep/split_tables.py data/extract$DAY/tables $R/tables $C/$A > $R/split.log 2>&1
    POLARS_MAX_THREADS=$t E_DIR=$R/tables/$C PREP_DIR=$R/prep_${C}_$DAY WORK_DIR=$R/work VALIDATE=0 \
      zsh sim/pipe_day.sh $DAY $NX $C $A $L > $R/pipe.log 2>&1
  ) &
done
wait
ok=1
for t in $TH; do
  R=$OUT/t$t
  grep -q "PIPE DONE" $R/pipe.log || { echo "run t$t did not finish:"; tail -3 $R/pipe.log; ok=0; }
  # every regular file the run wrote: the prep, the coin's tables dir (order binding, ledgers), the work dir
  (cd $R && find prep_${C}_$DAY tables/$C work -type f | sort | while read f; do md5s $f; done | awk '{print $1, $2}') > $OUT/hash_t$t.txt
done
ref=$OUT/hash_t${TH[1]}.txt
echo "$(wc -l < $ref | tr -d ' ') files per run, threads: $TH"
for t in ${TH[2,-1]}; do
  if diff -q $ref $OUT/hash_t$t.txt > /dev/null; then echo "t${TH[1]} vs t$t: identical"
  else echo "t${TH[1]} vs t$t: DIFFERENT"; diff $ref $OUT/hash_t$t.txt | grep '^[<>]' | awk '{print "   " $1, $3}' | sort -u; ok=0; fi
done
[[ $ok == 1 ]] && echo "DETERMINISM OK $C $DAY" || { echo "DETERMINISM FAILED $C $DAY"; exit 1; }
