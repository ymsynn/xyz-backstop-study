#!/bin/zsh
# Final rerun, step 1 on the Mac: the nine market-days whose inputs are only here (GOOGL 10-28, INTC / AMZN 10-29, the six
# quiet market-days of 10-20 and 10-21) are rebuilt with the reproducible pipeline, the way the EC2 job builds the others:
# the day's tables split per coin, then sim/pipe_day.sh. New preps go to data/rebuild/prep_{COIN}_{DAY}; nothing is overwritten.
cd "${0:A:h}/../.."; export PY=${PY:-python3}; R=$PWD/data/rebuild; mkdir -p $R
one() { # day next coin asset maxlev
  $PY -I sim/split_tables.py data/extract$1/tables $R/tables_$1 $3/$4 > $R/split_$3_$1.log 2>&1
  E_DIR=$R/tables_$1/$3 PREP_DIR=$R/prep_$3_$1 WORK_DIR=$R/work_$3_$1 VALIDATE=0 zsh sim/pipe_day.sh $1 $2 $3 $4 $5 > $R/pipe_$3_$1.log 2>&1
  echo "$3 $1: $(grep -c 'PIPE DONE' $R/pipe_$3_$1.log) $(tail -1 $R/pipe_$3_$1.log | cut -c1-80)"
}
one 1028 1029 GOOGL 110012 20 & one 1029 1030 INTC 110005 10 & one 1029 1030 AMZN 110013 20 & wait
one 1020 1021 GOOGL 110012 20 & one 1020 1021 INTC 110005 10 & one 1020 1021 AMZN 110013 20 & wait
one 1021 1022 GOOGL 110012 20 & one 1021 1022 INTC 110005 10 & one 1021 1022 AMZN 110013 20 & wait
echo REBUILD DONE; df -h / | tail -1 | awk '{print "free:", $4}'
