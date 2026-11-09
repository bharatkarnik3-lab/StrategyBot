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
5. In the last four turns, check one provable extra-capture opportunity. If
   capturing the neutral cell underfoot still leaves time for the selected
   neutral destination, adds more income than the one-turn delay costs, and
   rivals cannot interfere, take the extra capture. Do not apply this to raids
   or when it would displace another project.
6. Execute only the first action and replan from the next authoritative board.

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

## Validation recorded 9 November 2026

**The broader comparisons do not demonstrate a higher win rate.** The retained
change fixes a specific endgame decision without changing the earlier strategy.
In its regression scenario, taking an extra neutral cell before travelling to
another earns **475 points instead of 474**; both routes finish on time. Nearby
rivals, enemy-owned destinations and plans with additional projects disable this
shortcut. Broader experimental search and strategy changes did not establish a
reliable gain and are not part of this entry.

- **43 passing tests**: the original 35 checks, six fortress-opponent checks,
  and two endgame-regression/guard checks. Compilation and whitespace checks pass.
- **112 full candidate games**, including the original 32 and 80 additional
  games paired with the original bot from commit `876dee38448693b633e0b0d246a4ec753488117f`.
  Each run enforces legal actions, unchanged input snapshots and timing limits.
- Maximum candidate decision time across these runs: **9.824 ms** on this host,
  versus the 200 ms allowance. Timing is host-dependent.

| Suite | Maps / seats | Previous first places | Current first places | Current pairwise win rate |
| --- | --- | ---: | ---: | ---: |
| Original mixed baselines, seeds 20–27 | 8 maps × 4 seats | 25/32 | 25/32 | 91.67% |
| Additional mixed baselines, seeds 200–215 | 16 maps × 4 seats | 36/64 | 36/64 | 81.25% |
| Three fortress opponents, seeds 400–403 | 4 maps × 4 seats | 9/16 | 9/16 | 66.67% |

Mixed baselines are greedy expansion, upgrade-focused and raid-focused bots.
The fortress baseline captures and upgrades valuable territory and shields
eligible invaders; it uses only public state. Existing baseline behavior and
random-number streams are preserved for fair comparisons. First places include
ties; each pairwise score comparison counts as a win, loss or half-win for a tie.

[Machine-readable measurements](validation.json) record parameters, the previous
commit and the SHA-256 of the tested `bot.py`. Reproduce the paired comparisons:

```sh
git show 876dee38448693b633e0b0d246a4ec753488117f:bot.py > /tmp/strategybot_previous.py
python tools/compare.py --reference /tmp/strategybot_previous.py --maps 16 --seed 200
python tools/compare.py --reference /tmp/strategybot_previous.py --maps 4 --seed 400 --opponents fortress,fortress,fortress
```

Use `--head-to-head` to compare a candidate against three independent copies of
the reference bot. Every controller gets a fresh module per game. Run
`python -m unittest discover -s tests -v` for the regression suite; GitHub Actions
runs it on pushes and pull requests.

## Limits of these results

The simulator is an independent implementation of the published rulebook and
README, not the unpublished tournament server. The generated maps are mirrored
and use values 1–3, with generally stronger central cells; actual event maps may
differ. The baseline strategies are intentionally simple and do not represent
all competing teams. Neither the measurements nor the benchmark win rate
establish an optimal strategy, guarantee a win, or certify absence of bugs.
