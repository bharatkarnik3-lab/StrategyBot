# Strategy and validation

## Competition entry

Submit the repository containing `bot.py` through the organisers' normal process.
The entry retains `act(state)`, requires no third-party packages, and returns an
item from `state.legal_actions`. It never mutates the supplied game objects.
The matrix layout documented in the README is primary; the flat list described
in the original skeleton is also accepted.

## Decision process

1. Read the current board and locate all four bots. Reconcile previous requests
   with the actual outcome, including blocked moves, completed captures,
   upgrades and freeze/thaw transitions.
2. Use breadth-first routes that avoid cells occupied at the start of the turn.
   Estimate contested first steps using ownership, observed token rotation and
   rival movement likelihood. The legal-action list always takes precedence.
3. Search up to four capture/upgrade projects with a beam of twelve plans and
   up to eight continuations per plan. Score future income, raid bonuses, rival
   income denied, travel/stay cost, exposure and the defensive value of upgrades.
   Each hypothetical capture resets that cell's level before subsequent planning.
4. Compare a defensive shield against the planned action. Discount uncertain
   catches, exclude already frozen rivals, account for backfire risk, and avoid
   endgame shields against raids that cannot complete before the game ends.
5. Execute only the first action and replan from the next authoritative board.

Progress, cooldowns and the token are estimates when the interface does not
reveal them directly. Own stay progress uses observed position and cell changes,
so a failed move can count as a stay. Ambiguous freezes between other rivals do
not establish a shield cooldown. Opponent shielding is a risk estimate, not a
claim that their next action is known. The turn counter uses the documented
once-per-turn callback and globals-reset-per-game contract.

The search checks a monotonic 55 ms planning deadline and has small fixed width
and depth limits. This leaves headroom under the 200 ms allowance. The deadline
is a cooperative cutoff, not an operating-system hard real-time guarantee.
There is no randomness, training, network access, filesystem access or paid API
inside the competition entry. Tie-breaking is deterministic.

## Validation recorded 8 November 2026

- **35 passing unit/regression tests**, covering movement contests and no swaps,
  capture/upgrade timing, raid scoring, homes, simultaneous shields, two-turn
  freezes, four-turn cooldowns, memory reconciliation, legal outputs, input
  immutability, and endgame decisions.
- **32 full games**, eight seeded mirrored maps with all four candidate seats,
  against greedy expansion, upgrade-focused and raid-focused local baselines:
  **25 first places**, **91.67% pairwise win rate**, mean rank **1.25**, mean score
  **2552.88**. Pairwise rate counts each comparison with the other three players,
  with a tied score worth half a win.
- For those 2,560 candidate decisions: **2.342 ms p95**, **4.987 ms maximum** on
  the development host. These are measurements, not a hardware-independent bound.
- Four additional complete self-play games passed legality, immutability and
  timing checks, using a separately loaded module for each bot. Maximum measured
  decision time was **5.251 ms** for the sampled candidate seats.
- Python compilation and `git diff --check` passed. GitHub Actions runs the
  deterministic unit suite on pushes and pull requests.

Reproduce the benchmark using the commands at the end of the README. Runtime
measurements vary by host. Shield and exposure weights were selected through a
small bounded comparison on different seeds, rather than an unbounded search.

## Limits of these results

The simulator is an independent implementation of the published rulebook and
README, not the unpublished tournament server. The generated maps are mirrored
and use values 1–3, with generally stronger central cells; actual event maps may
differ. The baseline strategies are intentionally simple and do not represent
all competing teams. Neither the measurements nor the benchmark win rate
establish an optimal strategy, guarantee a win, or certify absence of bugs.
