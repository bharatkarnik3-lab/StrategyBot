"""Independent, unofficial Zone Rush reference model and repeatable benchmark.

Only bot.py is submitted. This model follows the published rules, not unpublished
server code. Snapshot objects expose only the documented input fields.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import random
import sys
import time
from types import SimpleNamespace

MOVES = {"NORTH": (-1, 0), "EAST": (0, 1), "SOUTH": (1, 0), "WEST": (0, -1)}
HOMES = (None, (0, 0), (0, 7), (7, 7), (7, 0))


@dataclass
class Cell:
    occupant: int = 0
    owner: int = 0
    is_upgraded: bool = False
    is_home: bool = False
    base_points: int = 1
    is_frozen: bool = False


def mirrored_map(seed=0):
    """Generate a mirror-symmetric map with generally stronger central cells."""
    rng = random.Random(seed)
    quadrant = [[max(1, min(3, 1 + (r + c) // 3 + rng.choice((-1, 0, 0, 0, 1))))
                 for c in range(4)] for r in range(4)]
    quadrant[0][0] = 1
    return [[quadrant[min(r, 7-r)][min(c, 7-c)] for c in range(8)] for r in range(8)]


class Game:
    def __init__(self, values=None, priority=1):
        values = values if values is not None else mirrored_map()
        self.board = [[Cell(base_points=values[r][c]) for c in range(8)] for r in range(8)]
        self.positions = list(HOMES)
        self.scores = [0] * 5
        self.progress = [0] * 5
        self.frozen = [0] * 5
        self.cooldown = [0] * 5
        self.priority = priority
        self.turn = 0
        for seat in range(1, 5):
            r, c = HOMES[seat]
            self.board[r][c].owner = seat
            self.board[r][c].is_home = True

    def legal_actions(self, seat):
        if self.frozen[seat]:
            return ["STAY"]
        r, c = self.positions[seat]
        actions = [name for name, (dr, dc) in MOVES.items() if 0 <= r+dr < 8 and 0 <= c+dc < 8]
        actions.append("STAY")
        if not self.cooldown[seat]:
            actions.append("SHIELD")
        return actions

    def state(self, seat):
        board = [[Cell(owner=cell.owner, is_upgraded=cell.is_upgraded,
                       is_home=cell.is_home, base_points=cell.base_points)
                  for cell in row] for row in self.board]
        for bot in range(1, 5):
            r, c = self.positions[bot]
            board[r][c].occupant = bot
            board[r][c].is_frozen = bool(self.frozen[bot])
        return SimpleNamespace(board=board, bot_id=seat,
                               is_priority_token=self.priority == seat,
                               legal_actions=self.legal_actions(seat))

    def step(self, actions):
        """Resolve a mapping {seat: action}; missing/illegal actions become STAY."""
        if self.turn >= 80:
            raise ValueError("The 80-turn game has finished")
        old_positions = self.positions[:]
        was_frozen = self.frozen[:]
        occupied = set(old_positions[1:])
        effective = {}
        claims = defaultdict(list)
        for seat in range(1, 5):
            action = actions.get(seat, "STAY")
            if action not in self.legal_actions(seat):
                action = "STAY"
            effective[seat] = action
            if action in MOVES:
                r, c = old_positions[seat]
                dr, dc = MOVES[action]
                dest = r+dr, c+dc
                if dest in occupied:
                    effective[seat] = "STAY"
                else:
                    claims[dest].append(seat)
        for (r, c), claimants in claims.items():
            owner = self.board[r][c].owner
            winner = owner if owner in claimants else min(claimants, key=lambda b: (b-self.priority) % 4)
            self.positions[winner] = (r, c)
            for loser in claimants:
                if loser != winner:
                    effective[loser] = "STAY"
        shielders = {seat for seat in range(1, 5) if effective[seat] == "SHIELD"}
        newly_frozen = set()
        for defender in shielders:
            caught = []
            for rival in range(1, 5):
                r, c = self.positions[rival]
                if (rival != defender and effective[rival] == "STAY" and
                        not was_frozen[rival] and self.board[r][c].owner == defender):
                    caught.append(rival)
            newly_frozen.update(caught or [defender])
        for seat in range(1, 5):
            r, c = self.positions[seat]
            cell = self.board[r][c]
            if was_frozen[seat] or seat in newly_frozen or effective[seat] != "STAY":
                self.progress[seat] = 0
                continue
            if cell.is_home and cell.owner != seat:
                self.progress[seat] = 0
                continue
            if cell.owner == seat:
                if cell.is_upgraded:
                    self.progress[seat] = 0
                else:
                    self.progress[seat] += 1
                    if self.progress[seat] >= 3:
                        cell.is_upgraded = True
                        self.progress[seat] = 0
            elif cell.owner in shielders:
                self.progress[seat] = 0
            else:
                self.progress[seat] += 1
                needed = 3 if cell.is_upgraded else 1
                if self.progress[seat] >= needed:
                    if cell.owner:
                        self.scores[seat] += 8 * cell.base_points * (2 if cell.is_upgraded else 1)
                    cell.owner, cell.is_upgraded = seat, False
                    self.progress[seat] = 0
        for row in self.board:
            for cell in row:
                if cell.owner:
                    self.scores[cell.owner] += cell.base_points * (2 if cell.is_upgraded else 1)
        for seat in range(1, 5):
            self.frozen[seat] = 2 if seat in newly_frozen else max(0, was_frozen[seat]-1)
            self.cooldown[seat] = 4 if seat in shielders else max(0, self.cooldown[seat]-1)
        self.priority = self.priority % 4 + 1
        self.turn += 1
        return effective


class Baseline:
    """Simple reproducible opponents; no privileged game-state information."""
    def __init__(self, kind="greedy", seed=0):
        self.kind, self.rng, self.turn = kind, random.Random(seed), 0
        self._fortress_previous = None
        self._fortress_progress = 0

    def act(self, state):
        self.turn += 1
        if self.kind == "fortress":
            return self._fortress_action(state)
        legal = state.legal_actions
        if legal == ["STAY"] or self.kind == "stay":
            return "STAY"
        if self.kind == "random":
            return self.rng.choice([a for a in legal if a != "SHIELD"])
        board, seat = state.board, state.bot_id
        start = next((r, c) for r in range(8) for c in range(8) if board[r][c].occupant == seat)
        if "SHIELD" in legal:
            intruders = [cell for row in board for cell in row if cell.owner == seat and
                         cell.occupant not in (0, seat) and not cell.is_frozen]
            if intruders and self.kind in ("greedy", "raider"):
                return "SHIELD"
        r, c = start
        here = board[r][c]
        if here.owner != seat and not here.is_home:
            return "STAY"
        if self.kind == "upgrade" and here.owner == seat and not here.is_upgraded:
            return "STAY"
        queue = deque([(start, 0, "STAY")])
        seen = {start}
        best, action = -float("inf"), "STAY"
        while queue:
            (r, c), distance, first = queue.popleft()
            cell = board[r][c]
            if not (cell.is_home and cell.owner != seat):
                if cell.owner != seat:
                    cost = distance + (3 if cell.is_upgraded else 1)
                    gain = cell.base_points * max(0, 81-self.turn-cost)
                    if cell.owner:
                        gain += 8*cell.base_points*(2 if cell.is_upgraded else 1)
                        if self.kind == "raider":
                            gain *= 1.7
                    score = gain / cost
                elif not cell.is_upgraded:
                    score = cell.base_points * max(0, 78-self.turn-distance) / (distance+3)
                else:
                    score = -1
                score += self.rng.random() * 1e-6
                if score > best:
                    best, action = score, first
            for name, (dr, dc) in MOVES.items():
                rr, cc = r+dr, c+dc
                if not (0 <= rr < 8 and 0 <= cc < 8) or (rr, cc) in seen:
                    continue
                if board[rr][cc].occupant not in (0, seat):
                    continue
                seen.add((rr, cc))
                queue.append(((rr, cc), distance+1, name if distance == 0 else first))
        return action if action in legal else "STAY"

    def _fortress_action(self, state):
        """Defend territory and finish valuable upgrades, with finite endgame costs.

        This stronger baseline only uses public snapshots. Its own progress is
        reconstructed from outcomes, including blocked moves and freeze resets.
        Existing baseline policies and their random-number streams are unchanged.
        """
        board, seat, legal = state.board, state.bot_id, state.legal_actions
        start = next((r, c) for r in range(8) for c in range(8)
                     if board[r][c].occupant == seat)
        here = board[start[0]][start[1]]
        current = (start, here.owner, here.is_upgraded, here.is_frozen)
        previous = self._fortress_previous
        if (previous is not None and previous[:3] == current[:3]
                and not previous[3] and not current[3]
                and previous[4] != "SHIELD"):
            self._fortress_progress += 1
            needed = 3 if here.owner == seat or here.is_upgraded else 1
            if self._fortress_progress >= needed:
                self._fortress_progress = 0
        else:
            self._fortress_progress = 0

        def choose(action):
            action = action if action in legal else ("STAY" if "STAY" in legal else legal[0])
            self._fortress_previous = current + (action,)
            return action

        remaining = 81 - self.turn
        if here.is_frozen or len(legal) == 1:
            return choose("STAY")
        if "SHIELD" in legal:
            intruders = [cell for row in board for cell in row
                         if cell.owner == seat and cell.occupant not in (0, seat)
                         and not cell.is_frozen and not cell.is_home
                         and (remaining >= 3 or not cell.is_upgraded)]
            if intruders:
                return choose("SHIELD")
        need = (3 if here.is_upgraded else 1) - self._fortress_progress
        if here.owner != seat and not here.is_home and need <= remaining:
            return choose("STAY")
        if (here.owner == seat and not here.is_upgraded and here.base_points >= 2
                and 3 - self._fortress_progress <= remaining):
            return choose("STAY")

        queue = deque([(start, 0, "STAY")])
        seen = {start}
        best, action = -float("inf"), "STAY"
        while queue:
            (r, c), distance, first = queue.popleft()
            cell = board[r][c]
            if not (cell.is_home and cell.owner != seat) and not (cell.owner == seat and cell.is_upgraded):
                stays = 3 if cell.owner == seat or cell.is_upgraded else 1
                if distance == 0:
                    stays = max(1, stays - self._fortress_progress)
                cost = distance + stays
                if cost <= remaining:
                    gain = cell.base_points * (remaining - cost + 1)
                    if cell.owner not in (0, seat):
                        gain += 8 * cell.base_points * (2 if cell.is_upgraded else 1)
                    score = gain / cost + self.rng.random() * 1e-6
                    if score > best:
                        best, action = score, first
            for name, (dr, dc) in MOVES.items():
                rr, cc = r+dr, c+dc
                if (not (0 <= rr < 8 and 0 <= cc < 8) or (rr, cc) in seen
                        or (distance == 0 and name not in legal)):
                    continue
                if board[rr][cc].occupant not in (0, seat):
                    continue
                seen.add((rr, cc))
                queue.append(((rr, cc), distance+1, name if distance == 0 else first))
        return choose(action)


def load_bot(path, name="candidate"):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def play(controllers, seed=0, check_inputs=False):
    """Controllers are four objects with act(state); returns game and timings."""
    game = Game(mirrored_map(seed), priority=seed % 4 + 1)
    elapsed = [[] for _ in range(4)]
    for _ in range(80):
        actions = {}
        for seat, controller in enumerate(controllers, 1):
            state = game.state(seat)
            before = repr(state) if check_inputs else None
            start = time.perf_counter()
            action = controller.act(state)
            duration = time.perf_counter() - start
            elapsed[seat-1].append(duration)
            if action not in game.legal_actions(seat):
                raise AssertionError(f"Seat {seat}, turn {game.turn+1}: illegal action {action!r}")
            if check_inputs and repr(state) != before:
                raise AssertionError(f"Seat {seat} mutated input")
            if duration > (2.0 if game.turn == 0 else 0.2):
                raise AssertionError(f"Seat {seat}, turn {game.turn+1}: deadline exceeded: {duration:.3f}s")
            actions[seat] = action
        game.step(actions)
    return game, elapsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bot", type=Path, default=Path(__file__).resolve().parents[1] / "bot.py")
    parser.add_argument("--games", type=int, default=16)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--opponents", default="greedy,upgrade,raider")
    parser.add_argument("--self-play", action="store_true")
    args = parser.parse_args()
    if args.games < 1:
        parser.error("--games must be positive")
    kinds = args.opponents.split(",")
    if len(kinds) != 3 or any(k not in {"greedy", "upgrade", "raider", "fortress", "random", "stay"} for k in kinds):
        parser.error("--opponents requires three of greedy,upgrade,raider,fortress,random,stay")
    scores, ranks, timings, pairwise, wins = [], [], [], 0, 0
    results = []
    for i in range(args.games):
        candidate_seat = i % 4
        seed = args.seed + i // 4
        controllers = [None] * 4
        for offset, kind in enumerate(kinds, 1):
            seat = (candidate_seat + offset) % 4
            controllers[seat] = Baseline(kind, seed*31+seat)
        if args.self_play:
            controllers = [load_bot(args.bot, f"bot_{i}_{j}") for j in range(4)]
        else:
            controllers[candidate_seat] = load_bot(args.bot, f"candidate_{i}")
        game, durations = play(controllers, seed, check_inputs=True)
        own = game.scores[candidate_seat+1]
        others = [s for j, s in enumerate(game.scores[1:]) if j != candidate_seat]
        rank = 1 + sum(s > own for s in others)
        pairwise += sum(1 if own > s else 0.5 if own == s else 0 for s in others)
        wins += rank == 1
        scores.append(own)
        ranks.append(rank)
        timings.extend(durations[candidate_seat])
        results.append({"seed": seed, "seat": candidate_seat+1, "scores": game.scores[1:], "rank": rank})
    timings.sort()
    print(json.dumps({"games": args.games, "first_places_including_ties": wins,
                      "pairwise_win_rate": round(pairwise/(3*args.games), 4),
                      "mean_score": round(sum(scores)/len(scores), 2),
                      "mean_rank": round(sum(ranks)/len(ranks), 3),
                      "decision_ms_p95": round(1000*timings[int(0.95*(len(timings)-1))], 3),
                      "decision_ms_max": round(1000*max(timings), 3),
                      "results": results}, indent=2))


if __name__ == "__main__":
    main()
