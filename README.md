# StrategyBot

This repository contains the starter code for **StrategyBot – Zone Rush**, a strategy and robotics competition organised by the **Aerospace & Robotics Club (ARC) × Coding Club** at **IIT Delhi – Abu Dhabi** as part of **AFKAR 2026**.

Zone Rush is played on an **8 × 8 board**. Coordinates follow Python's row–column indexing: `(0, 0)` is the **top-left corner**, and `(i, j)` denotes row `i`, column `j`. From `(i, j)`, the movement actions are:

| Action | New position |
| --- | --- |
| `NORTH` | `(i - 1, j)` |
| `SOUTH` | `(i + 1, j)` |
| `WEST` | `(i, j - 1)` |
| `EAST` | `(i, j + 1)` |

Each movement covers exactly one cell. **Diagonal moves and moves beyond the board's edges are not allowed.**

## Input

Your `act(state)` function receives a `state` object of class `Game`. The starter-code interface provides:

- **`state.board`**: An 8 × 8 two-dimensional list of `Cell` objects representing the board.
- **`state.bot_id`**: An integer from `1` to `4` identifying your bot's seat.
- **`state.is_priority_token`**: A Boolean indicating whether your bot currently holds the priority token.
- **`state.legal_actions`**: A list of action strings available to your bot on the current turn. The six possible actions are `"NORTH"`, `"EAST"`, `"SOUTH"`, `"WEST"`, `"STAY"`, and `"SHIELD"`.

`state.legal_actions` is never empty: **`"STAY"` is always available**. A frozen bot can only `STAY`.

### Cell attributes

Each element of `state.board` is a `Cell` object with these attributes:

| Attribute | Type | Description |
| --- | --- | --- |
| `cell.occupant` | `int` | Seat ID of the bot currently occupying the cell (`0` if unoccupied). |
| `cell.owner` | `int` | Seat ID of the bot that owns the cell (`0` if neutral). |
| `cell.is_upgraded` | `bool` | Whether the cell is upgraded to level 2 (worth double its base points). |
| `cell.is_home` | `bool` | Whether this is one of the four home cells, which cannot be captured by another bot. |
| `cell.is_frozen` | `bool` | Frozen status associated with the bot occupying this cell. **Freezing affects bots, not ownership or the cell itself.** |
| `cell.base_points` | `int` | Base points the cell earns per turn for its owner: `1`, `2`, or `3`. |

## Output

The `act(state)` function must return **exactly one string from `state.legal_actions`**.

## Rules

1. You may import modules from the **Python standard library** only; third-party packages are not permitted.
2. You may define your own functions and helper logic.
3. Do **not** change or remove the `act(state)` function signature.
4. Do **not** modify the input `state` object. Changes to the supplied state will not persist between turns.
5. Keep all of your bot's code in a single Python file named **`bot.py`**.
6. Do **not** rename `bot.py`.
7. For Round 1, keep `bot.py` in your team's own GitHub repository and submit the **repository link**, along with your team name, through the official Round 1 submission form. Upload your bot to the StrategyBot Arena as instructed by the organisers. The competition bot itself must remain a single Python file.

## Game Rules

The following summarises **Zone Rush**, as defined in **Section 2 of the official StrategyBot rulebook**. In the event of a discrepancy, **the official rulebook and the game server's official game record take precedence**.

1. **Board and objective:** Four bots compete on a mirrored **8 × 8 board** for **80 turns**. Each cell has a base value of `1`, `2`, or `3` points per turn. The aim is to finish with the highest cumulative score.
2. **Starting positions:** Bots start in the four corners, one per seat (`1`–`4`). Each bot permanently owns its corner **home cell**, which cannot be captured. Every other cell starts neutral.
3. **Actions and turn order:** All four bots choose an action simultaneously: `NORTH`, `EAST`, `SOUTH`, `WEST`, `STAY`, or `SHIELD`. The server resolves (a) movement and shields, (b) captures, upgrades, and freezes, (c) scoring, then (d) passes the priority token to the next seat (`1 → 2 → 3 → 4 → 1`).
4. **Movement and contested cells:** A bot may move one cell orthogonally or stay. A cell occupied **at the start of the turn** cannot be entered, even if its occupant is moving away; swaps are therefore impossible. If multiple bots try to enter the same initially empty cell, its owner wins the contest if one of the moving bots owns it. Otherwise, the first bot in seat order starting from the priority-token holder wins. Unsuccessful moves count as `STAY`.
5. **Capturing cells:** **Arriving on a cell does not count as a stay.** To capture a cell, the bot must use `STAY` on it for **1 turn** if it is neutral or an opponent's level-1 cell, or **3 turns** if it is an opponent's upgraded (level-2) cell. A captured cell becomes level 1. Home cells cannot be captured.
6. **Raid bonuses:** Taking an opponent's cell earns a one-time bonus of **`8 × cell.base_points × previous cell level`**. Capturing a neutral cell earns no raid bonus.
7. **Upgrading cells:** Using `STAY` for **3 turns on your own level-1 cell** upgrades it to **level 2**, doubling its points per turn. Capturing an upgraded cell resets it to level 1.
8. **`SHIELD` and freezing:** `SHIELD` protects **all of your cells** from being captured that turn. It also resets the progress of, and **freezes for 2 turns**, each eligible rival staying on your territory (including your home). A frozen bot can only `STAY`. If `SHIELD` catches no eligible rival—including when all rivals on your land are already frozen—it **backfires**, freezing your own bot for 2 turns. After using `SHIELD`, you cannot use it again for the **next 4 turns**. Moving off a cell, using `SHIELD`, or being frozen resets capture or upgrade progress; `SHIELD` itself does not count as `STAY`.
9. **Scoring and winning:** At the end of each turn, every owned cell earns its base points, **doubled if upgraded**. Raid bonuses are added when an opponent's cell is taken. After **80 turns**, the highest total score wins; tied totals share a place. No bot is eliminated during the game.

**Execution limits:** The server calls `act(state)` once per turn. Your code has **200 ms per turn**, except for the **first turn**, which allows **2 seconds**. If a bot crashes, exceeds its time limit, or returns an illegal action, that turn counts as `STAY`.

## Memory between turns: always trust ⁠ state ⁠

### What you can remember

•⁠  ⁠You can use global variables in ⁠ bot.py ⁠ to store information between turns.
•⁠  ⁠They keep their values for every turn of the same game (80 turns).
•⁠  ⁠They are cleared when a new game starts, so nothing carries over from one game to the next.
•⁠  ⁠Store your data in your own global variables, not in ⁠ state ⁠. ⁠ state ⁠ is rebuilt every turn.

### Why ⁠ state ⁠ is always right

The action your bot returns is a *request*. The server decides what actually happens, because only the server sees all four bots' actions at once. Your request may not happen exactly as you expect:

•⁠  ⁠*A move can fail.* Another bot wins the contested cell, or the cell was occupied at the start of the turn. Your bot stays where it was.
•⁠  ⁠*Late, crashed or illegal responses count as ⁠ STAY ⁠.*
•⁠  ⁠*A capture or upgrade can fail or be reset*, for example by a rival's ⁠ SHIELD ⁠.
•⁠  ⁠*Your bot can be frozen* by a rival's ⁠ SHIELD ⁠, or by your own ⁠ SHIELD ⁠ if it catches nobody.

Your bot is *not* told when any of this happens, so your global variables can become wrong. ⁠ state ⁠ is created by the server at the start of every turn, and it always shows the real game.

### What to do every turn

1.⁠ ⁠*Read ⁠ state ⁠ first.* Check where your bot actually is, which cells you own, which are upgraded, and whether you are frozen.
2.⁠ ⁠*Correct your global variables* wherever they disagree with ⁠ state ⁠.
3.⁠ ⁠*Then decide your move*, using ⁠ state.legal_actions ⁠.

For example, this finds your bot's actual position:

⁠ python
def my_position(state):
    for r in range(8):
        for c in range(8):
            if state.board[r][c].occupant == state.bot_id:
                return r, c
 ⁠

Useful checks: ⁠ cell.occupant ⁠ (who is on a cell), ⁠ cell.owner ⁠ (who owns it), ⁠ cell.is_upgraded ⁠, ⁠ cell.is_frozen ⁠, and ⁠ state.legal_actions ⁠ (what you are allowed to do this turn).
## Implemented bot and local validation

`bot.py` now implements a bounded planner for captures, upgrades, raids, contested
movement and defensive shields. It reads only the documented state fields and
uses the Python standard library. **Only `bot.py` is needed by the competition
runner**; it does not import the local simulator or tests, make network requests,
read files, or require API keys or paid services.

Use Python 3.10 or newer for the development tools:

```sh
python -m unittest discover -s tests -v
python tools/simulate.py --games 32 --seed 20 --opponents greedy,upgrade,raider
python tools/simulate.py --games 4 --seed 40 --self-play
python tools/simulate.py --games 16 --seed 400 --opponents fortress,fortress,fortress
```

The independent simulator checks legal actions, input immutability and per-turn
execution time while running complete games. It models the published rules;
**the organisers' server remains the authority**. Baseline results are useful
local comparisons, not predictions of tournament placement.

Use `tools/compare.py --reference /path/to/previous_bot.py` for paired comparisons
on identical maps and seats. The current revision fixes a verified endgame
decision; broader tests have not demonstrated a higher win rate.

See [strategy and validation notes](docs/STRATEGY.md) for the implementation,
observed results, and limitations. The official submission/arena upload remains
a separate step; committing code here does not submit an entry.
