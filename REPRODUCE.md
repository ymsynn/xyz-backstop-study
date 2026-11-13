# Reproducing the results

This file is written to be followed top to bottom by a person or by an automated agent. It says what data is needed,
where it lives, where each piece must be stored, which commands to run, and what to check at each step.

Nothing here needs data from the authors. Every input comes from two public archives and one file in this repository.

## 0. Ground rules

- **Read the raw archives only from AWS region `ap-northeast-1` (Tokyo).** Both are requester-pays buckets in that
  region. Read from an instance there, the transfer is free; read from anywhere else, you pay about $0.09 per GB, and a
  single day of the command stream is tens of GB. The jobs in `ec2/` do this for you. Do not `aws s3 cp` the raw
  archives to a laptop.
- **Every job in `ec2/` terminates its own instance** when it ends, fails, or reaches its time cap. After each one,
  confirm with `aws ec2 describe-instances --region ap-northeast-1 --filters Name=instance-state-name,Values=running`.
- **Jobs resume.** Each stage leaves a marker under `s3://$BUCKET/backstop/oos/done/`. Relaunching the same command
  continues where the last one stopped.
- All commands are run from the repository root.

## 1. What you need

| Need | Detail |
|---|---|
| AWS account | Permission to launch EC2 instances in `ap-northeast-1` and a spot quota of at least 32 vCPUs (one `r6i.8xlarge`). |
| S3 bucket | One bucket of your own in `ap-northeast-1`. The jobs write under `s3://$BUCKET/backstop/`. |
| Instance profile | A role the instances assume: `s3:GetObject` and `s3:ListBucket` on `hl-mainnet-node-data` and `hydromancer-reservoir`, read and write on your bucket, and `ec2:TerminateInstances`. |
| Local machine | 8 cores, 16 GB of memory, 12 GB of free disk. macOS or Linux, with `zsh`, Rust (stable), Python 3.12, the AWS CLI, and `tectonic` if you want to rebuild the PDF. |

```bash
cp config.example.env config.env        # then fill in BUCKET and INSTANCE_PROFILE
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
(cd engine && cargo build --release)
```

Set `PY` if your Python is not `python3` on the path, for example `export PY=$PWD/.venv/bin/python`.

## 2. The data

| Data | Where it lives | Used for | Where it ends up |
|---|---|---|---|
| Hyperliquid command stream, one folder per day | `s3://hl-mainnet-node-data/replica_cmds/<snapshot>/<YYYYMMDD>/*.lz4` | Every order, cancel and relayer update of the day | Read on the instance, reduced to tables in `s3://$BUCKET/backstop/oos/tables/<MMDD>/` |
| Hyperliquid explorer blocks | `s3://hl-mainnet-node-data/explorer_blocks/` | Filling a hole in the command stream (November 5 only) | Read on the instance |
| Hyperliquid ledger events | `s3://hl-mainnet-node-data/misc_events_by_block/hourly/<YYYYMMDD>/` | Deposits, withdrawals and transfers of each account | Read on the instance |
| xyz fills, liquidations, position snapshots, one-minute books | `s3://hydromancer-reservoir/by_dex/xyz/...` | Opening positions, real liquidations to compare with, book checks | Read on the instance |
| Account snapshots of all of Hyperliquid | `s3://hydromancer-reservoir/global/...` | Collateral of cross-margin accounts | Read on the instance |
| xyz market list | `data/xyzmeta.json` in this repository | Asset ids, maximum leverage, margin mode | Already in place |
| Venue trading hours | `data/venue_hours.json` in this repository | Scheduled closures of each external market | Already in place |

The output of the build is one folder per market-day, a *rebuilt market-day*, named `prep_<COIN>_<MMDD>`. The jobs
store them as `s3://$BUCKET/backstop/oos/preps_final/prep_<COIN>_<MMDD>.tgz`. The scorecard reads them from
`data/prep_<COIN>_<MMDD>/` on your machine. `data/` is git-ignored.

The list of market-days is in `ec2/market_days.env`.

## 3. Build the market-days (AWS, about $10, four to eight hours)

```bash
. ec2/market_days.env
```

Named events, quiet days and the out-of-sample days:

```bash
INSTANCE_TYPE=r6i.8xlarge VOLUME_GB=400 PAR=6 EXTRA_ENV="MAX_MIN=420 RUN_TAG=final SPLIT_PROCS=16 LEV_FIT_PROCS=10" DAYS="$DAYS_EVENTS" DAYS_DES="today" bash ec2/days_launch.sh
```

SK Hynix, July 27 (after the first job has ended, unless your spot quota allows two instances):

```bash
INSTANCE_TYPE=r6i.2xlarge VOLUME_GB=150 EXTRA_ENV="MAX_MIN=150 RUN_TAG=final SPLIT_PROCS=4 $ENV_SKHX" DAYS="$DAYS_SKHX" DAYS_DES="today" bash ec2/days_launch.sh
```

November 5, 33 markets, replayed on the instance under today's rules and the proposal:

```bash
INSTANCE_TYPE=r6i.8xlarge VOLUME_GB=400 PAR=16 EXTRA_ENV="MAX_MIN=300 RUN_TAG=final SPLIT_PROCS=16 LEV_FIT_PROCS=10" FILL_HOLES="$HOLES_1105" DAYS="$DAYS_1105" DAYS_DES="today lead3q1800" X_COINS="$SIX_MARKETS" CONTAGION=1 DETCHECK="BIRD/110063/10 SP500/110052/50" bash ec2/days_launch.sh
```

Each launch prints an instance id. Progress is one line in `s3://$BUCKET/backstop/oos/hb/<instance id>.txt`; the full
log is `s3://$BUCKET/backstop/oos/logs_job/oos_<instance id>.log`.

**Check before going on:**

- `aws s3 ls s3://$BUCKET/backstop/oos/done/ --region ap-northeast-1 | grep final_coin` lists 22 market-days for the
  first two jobs and 33 for November 5.
- The November 5 log contains `DETERMINISM OK` for BIRD and SP500: three builds with 1, 2 and 8 threads gave identical
  files.
- Each day's log has a line `coverage <MMDD> ok: ... holes none`. The job refuses a day whose tables do not start at
  the opening snapshot or have a gap.

## 4. Run the scorecard (local, about 90 minutes)

```bash
bash sim/final/fetch_days.sh            # 22 rebuilt market-days into data/, about 7 GB, roughly $0.70 of transfer
```

```bash
zsh sim/final/run_final.sh              # writes data/scen/final, about 3 GB
```

```bash
python sim/final/score_final.py data/scen/final
```

**Check:** the table printed by the last command against the first table of
[docs/results/scorecard.md](docs/results/scorecard.md). The walks and the normal sessions are scored by
`sim/score/ramp_eval.py` and `sim/score/normal_eval.py`; the exact calls are at the top of each section of that file. The
liquidation study behind the cut-back page is written by the run to `data/scen/final/liqstudy/eval.txt`.

The figures should match. Rebuilt on another EC2 instance, BIRD (November 5)
came out byte-identical to the published market-day in all 31 files, and its replays under both rule sets matched;
crude oil and Cloudflare (November 5) matched too, apart from one file left by an older build of the engine. One day's
tables rebuilt on macOS matched those built on Linux byte for byte.

## 5. The other results

| Result in the paper | Commands |
|---|---|
| 33 markets on November 5 | `aws s3 sync s3://$BUCKET/backstop/oos/joint_final/ data/scen/joint_final/ --region ap-northeast-1` (0.6 GB), then `JOINT_DIR=$PWD/data/scen/joint_final JOINT_DES="today lead3q1800" python sim/score/joint_eval.py 1105` |
| Random sample of market-days | Launch `ec2/days_launch.sh` with `DAYS="$DAYS_RANDOM" DAYS_DES="today lead3q1800"` and `EXTRA_ENV="MAX_MIN=240 RUN_TAG=random SPLIT_PROCS=16 LEV_FIT_PROCS=10 SKIP_BAD_DAYS=1 RELAYER_WARMUP_S=86400"`; sync `joint_random/` to `data/scen/joint_random/`; `python sim/final/score_random.py`. To redraw the sample itself: `SCRIPT=ec2/market_index.py PREFIX=random MAX_MIN=20 bash ec2/py_job_launch.sh`, copy `s3://$BUCKET/backstop/random/market_index.csv` to `data/random/`, `python sim/final/random_sample.py data/random/market_index.csv`. |
| A wrong external price that lasts 2, 5 and 15 minutes | `zsh sim/final/side_runs.sh` (output `data/scen/final/longprint`); compare with `docs/results/long_wrong_price.md` |
| Worst case: a lasting wrong price with a push on xyz's book | the same run of `sim/final/side_runs.sh` (output `data/scen/final/worstcase`); compare with `docs/results/worst_case_wrong_price_and_push.md` |
| The proposal without its correction step | `FINAL_OUT=$PWD/data/scen/final_k M=pkgm3k1800 D=lead3k1800 LIQ_DES="lead3k1800s20 lead3k1800" zsh sim/final/run_final.sh`, then `FINAL_OUT=$PWD/data/scen/final_k M=pkgm3k1800 D=lead3k1800 zsh sim/final/side_runs.sh`, then `SCORE_EXTRA="no_correction:pkgm3k1800:lead3k1800" python sim/final/score_final.py data/scen/final_k`; compare with `docs/results/correction_step.md` |
| xyz's whole book standing still during the crash | the same run of `sim/final/side_runs.sh` (output `data/scen/final/bookstill`); compare with `docs/results/book_still.md` |
| Change 2 alone under today's mark | `zsh sim/final/change2_alone.sh`; compare with `docs/results/change2_alone.md` |
| Crash with the largest market makers removed | `zsh sim/final/pull_check.sh`; compare with `docs/results/makers_pulled.md` |
| Value of positions when handed to the vault | `python sim/final/takeover_value.py`; compare with `docs/results/takeover_value.md` |
| July 27 by phase | `python sim/final/july27_phases.py`; compare with `docs/results/july27_phases.md` |
| Distinct traders where a count spans several markets | Every rebuilt market-day numbers its accounts from 0, so account numbers only mean something inside one market. `TAG=1105 MATCH="_1105" bash ec2/users_launch.sh` collects the address tables (`users.arrow`) from the market-day archives in S3 on one small self-terminating instance and writes `s3://$BUCKET/backstop/oos/users/users_1105.tgz` (a few MB); unpack it into `data/users/`, then `python sim/final/distinct_accounts.py` |
| The specification's test vector | `python3 docs/spec/three_vote_reference.py` checks the reference implementation against the engine's output on SK Hynix, July 27 (29,010 updates) |
| Rule explorer data | `zsh viewer/run_grid.sh`, `zsh viewer/run_attacks.sh` (long: 180 replays; keep the default parallelism of 3 on a 16 GB machine), then `python viewer/build_data.py` |
| Cost of clearing one side of the book | `zsh sim/final/depth_runs.sh`, then `python sim/final/depth_eval.py`; compare with `docs/results/book_depth.md` |
| What the mark does when one side of the book is empty | `SCRIPT=ec2/onesided_screen.py PREFIX=onesided INSTANCE_TYPE=c6i.xlarge MAX_MIN=90 bash ec2/py_job_launch.sh`, then the same with `SCRIPT=ec2/onesided_confirm.py PREFIX=onesided`; outputs under `s3://$BUCKET/backstop/onesided/` |
| ADL history over 392 days | `bash ec2/tape_launch.sh`, then `python sim/score/tape_eval.py` |
| Vault capital, eligible markets, external-price quality (changes 4 to 6) | `sim/study/vault_capital.py`, `sim/study/joint_capital.py`, `sim/study/capital_risk.py`, `sim/study/cross_eligibility.py`, `sim/study/e_quality.py`; each file's header gives its inputs and usage. |
| Figures and PDFs | `python sim/figs.py`, then `cd docs && tectonic mark_formulas.tex && tectonic variant_history.tex` |

## 6. Things that will trip you

- **Whole-day replays need the relayer simulated for the whole day.** By default the engine simulates trade.xyz's
  relayer from 17:45 UTC, the window of the earnings crashes. For a market-day where the external price is not live
  before that hour (a weekend, a holiday, an Asian market), set `RELAYER_WARMUP_S=86400`. The scripts in `sim/final/`
  already set the right value for each test.
- **Days before about July 20, 2026 cannot be built.** The command stream of those days has a layout the extractor
  does not read; the job reports `extract <MMDD> had failures` and, with `SKIP_BAD_DAYS=1`, moves to the next day.
- **November 5 needs `FILL_HOLES`.** Without it the coverage check stops the day.
- **The engine build must succeed on the instance.** The job stops at once with `ENGINE BUILD FAILED` if it does not;
  relaunch.
- **zsh, not bash,** for the scripts under `sim/` and `tools/`.
- **Memory.** `tools/memguard.sh` kills a replay whose process tree passes its cap, 12 GB for every runner. On a 16 GB machine do not raise the parallelism
  of `run_final.sh`.

## 7. Cost and time, as we measured them

| Step | Time | Cost |
|---|---|---|
| Building one day (extraction, tables, market-days) on `r6i.8xlarge` spot | 10 to 30 minutes | about $0.30 |
| November 5, 33 markets under both rule sets, with the second pass | 1 hour | about $0.90 |
| Rebuilt market-days to a laptop, 7 GB | minutes | about $0.70 |
| Scorecard on an 8-core laptop | 90 minutes | none |
