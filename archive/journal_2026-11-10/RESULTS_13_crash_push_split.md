# 2026-11-11: the crash book push, split between the attacker, the other traders and the vault
Runner: data/scen/tests_1110f/fl/push5/run.sh (copy: run_crash_push_split.sh). Scorer: score_push_split.py. Fixed engine
(unrounded internal oracle, ONE_SIDED=quote). GOOGL 10-28: a margined account (20x) bids 6% above xyz's mid from 5 s before
the crash, for 60 s or 300 s. Attacker's account id in the outputs: 4294967286.

| $5M attacker, 60 s / 300 s              | today         | previous      | no ratchet     | full ratchet  | candidate (book-aware) |
|-----------------------------------------|---------------|---------------|----------------|---------------|------------------------|
| Attacker buys, $M                       | 62.4          | 51.4          | 64.3 / 72.9    | 49.9          | 64.3 / 65.6            |
| Attacker's capital lost                 | 5.00 (all)    | 4.82 (96%)    | 5.00 (all)     | 5.00 (all)    | 5.00 (all)             |
| Attacker's position taken over, $M      | 39.3          | 0             | 29.3 / 48.5    | 7.6           | 29.4 / 28.9            |
| Largest mark lift bp / seconds above 1% | 60 / 0        | 48 / 0        | 515 / 63       | 292 / 27      | 395 / 45               |
| Other accounts liquidated by the push   | 1             | 1             | 0              | 0             | 0                      |
| Other traders' takeovers, change $M     | -1.02         | -0.72         | +1.80          | +0.05         | +0.56                  |
| Vault capital need $M (without push)    | 0.90 (0.33)   | 0.36 (0.42)   | 0.82 / 1.18 (0.41) | 0.50 (0.42) | 0.79 / 0.84 (0.42)   |
| Vault need to avoid ADL $M (without)    | 0.08 (0.18)   | 0.17 (0.22)   | 0.14 / 0.11 (0.22) | 0.19 (0.22) | 0.14 (0.22)          |
| Inherited by the vault $M, of which the attacker's | 44.3, 39.3 | 8.6, 0   | 40.3, 29.3 / 59.5, 48.5 | 16.9, 7.6 | 39.3, 29.4 / 38.8, 28.9 |

| $1M attacker (60 s = 300 s)             | today         | previous      | no ratchet     | full ratchet  | candidate              |
|-----------------------------------------|---------------|---------------|----------------|---------------|------------------------|
| Attacker's capital lost                 | 1.00 (all)    | 1.00 (all)    | 1.00 (all)     | 1.00 (all)    | 1.00 (all)             |
| Largest mark lift bp                    | 20            | 20            | 7              | 0             | 0                      |
| Vault capital need $M (without push)    | 0.81 (0.33)   | 0.86 (0.42)   | 0.86 (0.41)    | 0.86 (0.42)   | 0.86 (0.42)            |
| Inherited $M, of which the attacker's   | 15.0, 9.0     | 18.4, 9.2     | 18.7, 9.3      | 18.8, 9.3     | 18.8, 9.3              |

Reading:
- The attacker loses everything: $5M of $5M in every design but the previous candidate (96%), $1M of $1M in all five.
- Nobody else is hurt: no other account is liquidated by the push under the three-vote versions (1 under today's rules and the
  previous candidate); other traders' takeovers change by +$0.56M under the candidate.
- The vault's capital need rises by $0.37-0.42M under the candidate ($0.48-0.57M today) because it inherits the attacker's own
  position ($29M of the $39M). The need to avoid ADL falls.
- With $1M the five designs are the same: need 0.81-0.86 $M, set by the attacker's $9M position, not by the mark.
So this is a leveraged buyer wiped out in a crash, not an attack that pays: $5M spent to raise the vault's capital need by
about $0.4M for a few minutes. It is a stress case for the vault (how large a single position it may inherit at once), and the
designs differ only in how much of that position reaches the vault rather than the book.
