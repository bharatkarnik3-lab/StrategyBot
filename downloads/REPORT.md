# StrategyBot: shield-aware candidate

This new single-file bot is derived from the supplied `bot_dev.py`. The repository was not changed.

## Changes

- Tracks shield probability separately for stays that would complete a capture. Earlier safe stays no longer teach it that the completing stay is safe.
- Records confirmed catches on upgraded rival territory. Once a defender is known, another upgraded raid is rejected unless its remaining movement and stays fit entirely inside a confirmed shield-unavailable window.
- Leaves a locked raid after thawing when an escape route exists; does not merely move the same bad raid to another upgraded cell belonging to that defender.
- Avoids invented opponent cooldowns after backfires or ambiguous freezes. Frozen turns reset progress as the rulebook requires.
- Corrects endgame shield decisions and caps costs/benefits at the end of the game.

## Fresh direct comparisons

Candidate code was frozen before testing seeds 1000–1015. Every reference played 96 games: two independent copies of each program, across all six seat allocations. The main metric is the candidate’s share of the four cross-program score comparisons in each game, with ties worth half a win. It is **not a first-place game percentage**.

| Reference | Candidate pairwise score | Mean score margin | Candidate frozen turns | Reference frozen turns | Max same-cell catches: candidate / reference |
| --- | ---: | ---: | ---: | ---: | ---: |
| Uploaded bot_dev.py | 57.3% | +48.7 | 1.24 | 4.45 | 1 / 8 |
| Uploaded mbot.py | 88.8% | +600.5 | 2.12 | 16.04 | 1 / 13 |
| Previous repository bot | 90.4% | +472.3 | 2.81 | 13.89 | 1 / 12 |

Frozen-turn means are per bot per game. The repeat-catch metric is the largest count for one defender/cell in a game. The candidate’s maximum was one throughout these comparisons.

## Separate shield-heavy stress suite

Each program also played 32 games against three patient defenders on seeds 2000–2007, rotating its seat. These defenders save SHIELD for the stay that would complete a raid.

| Program | First places | Pairwise score | Mean frozen turns | Max same-cell catches |
| --- | ---: | ---: | ---: | ---: |
| New candidate | 19/32 | 85.4% | 0.78 | 1 |
| bot_dev.py | 21/32 | 87.5% | 1.44 | 3 |
| mbot.py | 19/32 | 79.2% | 7.09 | 8 |
| Previous bot | 7/32 | 47.9% | 6.84 | 10 |

**Limit:** bot_dev.py achieved more first places in this separate stress suite (21 versus 19). The candidate won the direct comparisons and sharply reduced repeated freezes; these results do not establish that it wins against every opponent or map.

## Correctness and runtime

- 34 passing tests: 21 simulator rule tests, seven tracker/endgame tests, and six raid-lock tests.
- The lock regression forces an initial interrupted three-stay raid, checks the two frozen turns, verifies escape on the first thaw, then runs another 22 turns against a completing-stay defender. The bot expands into neutral territory and is not caught again on the locked cell.
- Tests verify cooldown windows include travel time, other upgraded cells of the same defender inherit the lock, frozen stays do not dilute urgent shield estimates, and a surrounded bot still returns a legal action.
- All evaluation calls checked legal output, input immutability, exceptions and the 200 ms turn limit (2 seconds on the first turn). Hidden caught exceptions in the supplied development bot were made test failures.
- Maximum measured candidate decision time: 40.592 ms. The bot uses only the Python standard library and requires no paid API or network connection.

## Reproduce

Only `bot.py` is needed by the competition runner. Extract the validation bundle and use Python 3.10+ for its test tools:

```sh
python -B -m unittest discover -p "test_*.py" -v
python -B arena.py bot.py references/bot_dev.py --seed 1000 --maps 16 --output duel_dev.json
python -B arena.py bot.py references/mbot.py --seed 1000 --maps 16 --output duel_mbot.json
python -B arena.py bot.py references/bot_current.py --seed 1000 --maps 16 --output duel_previous.json
python -B run_shield_stress.py
```

The JSON results include every game, reference hashes and a bootstrap interval that resamples whole maps, rather than pretending seat-level comparisons are independent. Development used separate seeds (0–3, 12–13, 20–25 and 30–31). The final holdout seeds were not used to select weights.

The simulator implements the public rulebook and is not the unpublished official server. Generated maps are mirrored with values 1–3 and generally stronger centers. Runtime varies by host. A legal escape cannot be guaranteed if all neighboring cells are closed or an opponent wins a simultaneous movement contest.

Candidate SHA-256: `de52225aa4fb369d1673b963e7b0486e49d9c3dfa72e07e93822b27928350e6a`
