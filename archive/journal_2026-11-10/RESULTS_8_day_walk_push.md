# Why the daytime walk + $5M book push shows $11.4M of extra takeovers under the candidate (today: $6.2M)
2026-11-10 night. No new runs: breakdown of data/scen/tests_1110h/adapt_day and tests_1110i/down_day (GOOGL 10-28, feed walked
-10% over 30 s from 22:30 UTC and held 120 s, attacker offers 10% below the mid for 60 s once the walk is complete).
Window: 300 s from the start of the walk. Shares at about $290.

| Positions liquidated in the window        | today, walk alone | today, walk + push | previous, walk alone | previous, walk + push | candidate, walk alone | candidate, walk + push |
|-------------------------------------------|-------------------|--------------------|----------------------|-----------------------|-----------------------|------------------------|
| Accounts liquidated                       | 520               | 672                | 691                  | 702                   | 0                     | 717                    |
| ... taken over by the vault               | 4                 | 339                | 88                   | 141                   | 0                     | 713                    |
| Shares sold on xyz's book                 | 24,466            | 15,393             | 25,357               | 24,664                | 0                     | 1,902                  |
| Shares taken over by the vault            | 4,011             | 27,049             | 17,313               | 20,199                | 0                     | 41,880                 |
| Total liquidated, shares ($M)             | 28,478 (8.3)      | 42,442 (12.3)      | 42,670 (12.4)        | 44,864 (13.0)         | 0                     | 43,782 (12.7)          |
| Vault capital need over the day $M        | 0.33 (unchanged)  | 0.47               | 0.42 (unchanged)     | 0.43                  | 0.42 (unchanged)      | 0.54                   |
| Vault need to avoid ADL over the day $M   | 0.20              | 0.30               | 0.29                 | 0.31                  | 0.22                  | 0.27                   |
(no attack: capital need 0.33 today, 0.42 previous and candidate; need to avoid ADL 0.18 / 0.22 / 0.22)
With a 15 s push: candidate 157 accounts, 10,513 shares ($3.0M); today 600 accounts, 38,071 shares ($11.0M).

Reading: "extra takeovers" counts only what the vault takes, not what is sold on the book. Once feed and book both sit 10% low
for a minute the same positions are liquidated in every design (662 of the candidate's 717 accounts are also liquidated under
today's rules; $12.3-13.0M in all three). Under today's rules and the previous candidate most of them are already liquidated
by the walk alone ($8.3M / $12.4M, no book push needed), through a book that still has bids. Under the candidate the walk
liquidates nobody; the liquidations only come with the push, when the attacker has emptied the bid side, so they go to the
vault instead of the book (1,902 shares on the book). The candidate is not weaker here: it needs the $5M push where today needs
none, and its vault needs +0.12 $M of capital in the attack against +0.14 today. What changes is who takes the positions.
