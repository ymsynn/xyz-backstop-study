# The moments of the replayed market-days, in epoch milliseconds, for the runners that start an attack or a window at one
# of them. Named here so that a reader can tell what a runner's start time is without converting it, and so that the same
# moment is one value everywhere. Each comment gives the local time of the market the day belongs to.
# Sourced after the runner's `cd` to the repository root: `source $PWD/sim/times.zsh`.

# Alphabet, Wednesday October 28 (US Eastern; the cash session closes at 16:00)
GOOGL_CLOSE=1793217600000        # 16:00, the close: the earnings crash begins
GOOGL_CLOSE_10M=1793218200000    # 16:10
GOOGL_EVE=1793226600000          # 18:30, the bad-print hour of sim/runs/spike_runs.sh
GOOGL_PREV_EVE=1793146200000     # Tuesday 20:10, the evening before
GOOGL_NIGHT=1793163600000        # 01:00, the venue closed
GOOGL_NIGHT_10M=1793164200000    # 01:10

# Amazon and Intel, Thursday October 29 (US Eastern; both markets share the day)
AMZN_CLOSE=1793304000000         # 16:00, the close
AMZN_CLOSE_10M=1793304600000     # 16:10
AMZN_EVE=1793313000000           # 18:30
AMZN_PREV_EVE=1793232600000      # Wednesday 20:10, the evening before
AMZN_NIGHT=1793250000000         # 01:00, the venue closed

# The other days
GOLD_EVE=1793397600000           # Friday October 30, 18:00 US Eastern: gold's venue closed
CL_CLOSED=1789074600000          # Thursday September 10, 17:10 US Eastern: crude oil's venue closed
SKHX_OPEN=1785111000000          # Monday July 27, 09:10 in Seoul: SK Hynix's market open
SKHX_NOON=1785121200000          # Monday July 27, 12:00 in Seoul

# Milliseconds from the close to the first print of the crash: each market's own onset (the attacks start 5 s before it)
GOOGL_ONSET_MS=118800
INTC_ONSET_MS=66800
AMZN_ONSET_MS=63900
