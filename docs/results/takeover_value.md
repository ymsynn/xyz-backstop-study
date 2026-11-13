# What the vault is handed: takeovers valued at the external price

`python sim/final/takeover_value.py`, on the final run (`data/scen/final`, proposal without the earlier hold rule), 2026-11-12. For each takeover: the position
valued at the external price at that instant, minus the price the vault takes it at. "Below the external price" counts
the takeovers where that value is negative, that is, positions already worth less than the vault pays for them.

This is the state of the positions when they reach the vault. It is not the vault's result, which depends on how it
sells afterwards and cannot be tested on a replayed book.

| Event | Rules | Takeovers | Below the external price | Inherited $M | Value when handed to the vault $k |
|---|---|---|---|---|---|
| Alphabet, October 28 | today | 158 | 156 | 6.96 | -46.8 |
| Alphabet, October 28 | today's mark, cut-back | 184 | 180 | 7.83 | -53.7 |
| Alphabet, October 28 | proposal's mark, 20% slices | 255 | 12 | 12.13 | +110.0 |
| Alphabet, October 28 | proposal | 258 | 12 | 10.28 | +77.7 |
| Intel, October 29 | today | 258 | 258 | 2.24 | -60.9 |
| Intel, October 29 | today's mark, cut-back | 258 | 258 | 2.02 | -58.9 |
| Intel, October 29 | proposal's mark, 20% slices | 29 | 23 | 0.38 | +7.6 |
| Intel, October 29 | proposal | 29 | 23 | 0.30 | +6.8 |
| Amazon, October 29 | today | 403 | 400 | 1.55 | -50.2 |
| Amazon, October 29 | today's mark, cut-back | 403 | 400 | 1.55 | -50.2 |
| Amazon, October 29 | proposal's mark, 20% slices | 296 | 287 | 1.33 | -21.1 |
| Amazon, October 29 | proposal | 296 | 287 | 1.32 | -21.1 |
| SK Hynix, July 27 | today | 352 | 349 | 15.90 | -1786.7 |
| SK Hynix, July 27 | proposal | 595 | 586 | 19.05 | -2445.6 |
| Three earnings crashes | today | 819 | 814 | 10.75 | -157.9 |
| Three earnings crashes | today's mark, cut-back | 845 | 838 | 11.41 | -162.8 |
| Three earnings crashes | proposal's mark, 20% slices | 580 | 322 | 13.84 | +96.4 |
| Three earnings crashes | proposal | 583 | 322 | 11.90 | +63.4 |

Limits. The dollar values are small beside the amounts inherited, and of the same order as the replay's own error (on
November 5 it created a $0.51M takeover that did not happen), so the counts carry more weight than the sums. On SK Hynix
the external price at the reopening is the one the paper describes as bad, so a value measured against it is doubtful
for that day. Amazon stays mostly below the external price under both sets of rules.
