# StrategyBot improvement — 12 November 2026

## What to use

Submit only `bot.py`. It is a single standard-library Python file exposing `act(state)`.
It needs no external package, training service, API key, or paid API call.

## Changes and online research

The final candidate combines the previously delivered anti-shield planner with a new
finite-horizon beam search for the last 12 turns. Each turn it evaluates sequences of
captures/upgrades, executes the first move, and replans from the next real snapshot.
It ranks these late sequences by total remaining utility rather than average utility
per turn. Paths avoid currently occupied cells, hypothetical captures update a private
board, and the search retains a valid fallback when its budget expires.
The beam width is 24, depth is at most 6 follow-up projects, and the evaluation budget
is approximately 4,000 (checked per node), with an elapsed-time deadline as well.
This is approximate search with heuristic opponent risk, not an exact solver.

Targeted online searches found no reliable strategy guide for this exact ARC × Coding
Club Zone Rush competition. Similarly named games found online were unrelated.
The implementation uses general research ideas, not copied competition bot code:

- [Liu, Pérez-Liébana and Lucas (2016), Rolling Horizon Coevolutionary Planning](https://arxiv.org/abs/1607.01730): evaluate action sequences, execute the first action, then replan. Our adaptation uses deterministic project-level beam search; it does not implement their coevolution algorithm.
- [Tang et al. (2020), Enhanced Rolling Horizon Evolution with Opponent Model Learning](https://arxiv.org/abs/2003.13949): condition plans on opponent behavior. Here the existing lightweight shield model learns final-stay behavior separately; no neural network or policy-gradient training is used.
- [Goodman and Lucas (2020), Opponent Modelling in an RTS game](https://arxiv.org/abs/2006.08659): inaccurate opponent assumptions can degrade planning. This motivated testing the more complex uploaded model against the simpler previous model and rejecting the weaker variant. Their empirical finding is from another game, not proof about Zone Rush.

Compared with the supplied upload, the retained raid model also prevents false cooldowns
from ambiguous freezes, learns completing-stay shield risk without dilution by harmless
early stays, applies confirmed shield traps across an owner's upgraded cells, allows
raids only within verified safe windows after a catch, and caps shield value at game end.

## Development and selection

A small initial comparison used seeds 3010–3013. A candidate derived directly from the
upload passed its regression tests but only scored 51.6% pairwise against the upload
and 36.5% against the November 9 release in expanded testing. It was rejected.
The final candidate retains the November 9 raid model and adds the new search.
Fresh final evaluation seeds below were used after that choice. No parameter sweep,
paid training service, or online adaptation to benchmark source files was used.
Experimental results are included separately; they are not results for the final file.

## Final evaluation

The independent local simulator implements the published rules; it is not the official
competition server. Each direct match contains two isolated copies of each program.
Every map uses all six seat allocations. Pairwise rate compares each candidate score
to each opponent score, ties counting half; it is **not a first-place game win rate**.

| Opponent | Games | Pairwise rate | Mean score margin | Frozen turns: new / reference |
|---|---:|---:|---:|---:|
| Uploaded bot.py | 72 | 54.2% | +23.0 | 1.54 / 1.73 |
| Previous delivered bot | 48 | 51.0% | +6.1 | 1.42 / 1.39 |
| bot_dev.py | 24 | 65.1% | +77.5 | 2.06 / 6.69 |
| mbot.py | 24 | 92.7% | +702.0 | 1.90 / 19.15 |

Final seed ranges: upload 5100–5111; previous 5200–5207; bot_dev and mbot 5300–5303.

Additional patient-shield defenders (seeds 5400–5403, every seat):

- bot.py: 8/16 first places; 79.2% pairwise; 0.56 frozen turns on average; maximum 1 catches on the same upgraded cell.
- references/uploaded.py: 9/16 first places; 83.3% pairwise; 0.25 frozen turns on average; maximum 1 catches on the same upgraded cell.

All 40 packaged tests pass. Match harnesses check legal actions, unchanged input state,
internal exceptions (including silently caught exceptions), and the per-turn deadline.
Maximum observed final-candidate call time was 44.4 ms on this machine (200 ms rule,
2 seconds on turn one). These times are measurements, not guarantees on other hardware.

These are finite local samples, not proof of universal superiority. Whole-map bootstrap
intervals are recorded in validation_summary.json; small samples, repeated seats and
opponent-specific behavior limit confidence. The beam assumes current occupancy persists
for its short plans and approximates future shield decisions. Forced movement contests
and genuinely blocked exits can still prevent escape. Raw scores and every tested matchup
are included so improvements and regressions can be inspected.

Candidate SHA-256: `070874df75a4c09d67a0300646abfa31d6dd4ab68247b344021413ad13b134cd`.
