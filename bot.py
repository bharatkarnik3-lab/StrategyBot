"""Zone Rush competition entry: standard library only, one file, no I/O.

The board is authoritative. Memory only estimates hidden stay progress, elapsed
turns and observed shield cooldowns. Each turn replans a short beam of capture
and upgrade projects; only the first legal action is returned.
"""

from collections import deque
from time import perf_counter

_TURNS = 80
_DIRECTIONS = (("NORTH", -1, 0), ("EAST", 0, 1),
               ("SOUTH", 1, 0), ("WEST", 0, -1))
_NEIGHBORS = tuple(
    tuple((name, (i // 8 + dr) * 8 + i % 8 + dc)
          for name, dr, dc in _DIRECTIONS
          if 0 <= i // 8 + dr < 8 and 0 <= i % 8 + dc < 8)
    for i in range(64)
)
_MEMORY = {}


def _snapshot(state):
    # README specifies a matrix; also accept the flat list mentioned in the
    # original skeleton's docstring. Never write to the supplied cells.
    board = state.board
    cells = [cell for row in board for cell in row] if len(board) == 8 else list(board)
    return tuple((c.owner, bool(c.is_upgraded), c.occupant,
                  bool(c.is_frozen), bool(c.is_home), c.base_points)
                 for c in cells)


def _observe(board, bot_id, legal, priority):
    positions = {c[2]: i for i, c in enumerate(board) if c[2]}
    pos = positions.get(bot_id)
    old = _MEMORY.get(bot_id)
    if old is None:
        old = {"turn": -1, "board": None, "progress": {}, "shields": {},
               "token": None, "action": None}
    turn = old["turn"] + 1
    previous = old["board"]
    progress = {}
    shields = dict(old["shields"])
    if previous is not None:
        old_positions = {c[2]: i for i, c in enumerate(previous) if c[2]}
        for seat, square in positions.items():
            now = board[square]
            before = previous[square]
            same = old_positions.get(seat) == square
            if now[3] and same and not before[3]:
                # Attribute a new freeze only when the visible outcome and
                # our own action distinguish a shield from a backfire.
                owner = now[0]
                if seat == bot_id:
                    source = seat if old["action"] == "SHIELD" else owner
                elif not owner or owner == seat:
                    source = seat  # Backfire on neutral or own land.
                elif owner == bot_id:
                    source = owner if old["action"] == "SHIELD" else seat
                else:
                    source = None  # Another rival's shield versus backfire is hidden.
                if source:
                    shields[source] = turn - 1
            if (same and not now[3] and not before[3]
                    and now[:2] == before[:2]
                    and not (seat == bot_id and old["action"] == "SHIELD")):
                need = 3 if now[0] == seat or now[1] else 1
                p = old["progress"].get(seat, 0) + 1
                if not (now[4] and now[0] != seat) and not (now[0] == seat and now[1]):
                    # If an expected completion is absent, discard the estimate.
                    progress[seat] = p if p < need else 0
        if old["action"] == "SHIELD":
            shields[bot_id] = turn - 1
    token = bot_id if priority else (
        old["token"] % 4 + 1 if old["token"] is not None else None)
    # An inconsistent flag invalidates an inferred token rather than overruling
    # the supplied state (also useful when inspecting a mid-game snapshot).
    if token == bot_id and not priority:
        token = None
    memory = {"turn": turn, "board": board, "progress": progress,
              "shields": shields, "token": token, "action": None}
    _MEMORY[bot_id] = memory
    return memory, positions, pos


def _paths(source, blocked, legal=None):
    distances = [99] * 64
    first = [None] * 64
    distances[source] = 0
    first[source] = "STAY"
    queue = deque([source])
    while queue:
        current = queue.popleft()
        for action, target in _NEIGHBORS[current]:
            if (target in blocked or distances[target] != 99
                    or (current == source and legal is not None and action not in legal)):
                continue
            distances[target] = distances[current] + 1
            first[target] = action if current == source else first[current]
            queue.append(target)
    return distances, first


def _stay_probability(cell, seat, progress):
    if cell[3]:
        return 0.0  # Already frozen opponents cannot be caught.
    if cell[0] != seat:
        if cell[4]:
            return 0.08
        return 0.94 if not cell[1] or progress else 0.72
    return 0.30 if not cell[1] else 0.10


def _shield_value(board, bot_id, positions, memory, remaining):
    """Expected benefit, in the same point-per-action units as the planner."""
    no_catch = 1.0
    benefit = 0.0
    for seat, square in positions.items():
        cell = board[square]
        if seat == bot_id or cell[0] != bot_id or cell[3]:
            continue
        stays_needed = 3 - memory["progress"].get(seat, 0) if cell[1] else 1
        if remaining < stays_needed or (cell[4] and remaining == 1):
            continue
        probability = _stay_probability(cell, seat, memory["progress"].get(seat, 0))
        no_catch *= 1.0 - probability
        level = 2 if cell[1] else 1
        # Shield buys three non-productive rival turns, and often saves an
        # imminent capture. A delayed raid can still happen after thawing.
        imminent = not cell[1] or memory["progress"].get(seat, 0) >= 2
        saved = min(remaining, 6 if imminent else 3) * cell[5] * level
        if imminent and not cell[4]:
            saved += 0.80 * remaining * cell[5] * level
        raid = 8 * cell[5] * level if imminent and not cell[4] else 0
        benefit += probability * (0.65 * saved + 0.45 * raid + 4.0 * min(2, remaining - 1))
    if no_catch == 1.0:
        return -1.0
    # Failure also costs the two following turns. Requiring a likely catch
    # makes shielding selective even when SHIELD happens to be legal.
    return benefit - no_catch * 35.0


def _plan(board, bot_id, pos, positions, memory, legal, deadline):
    remaining = max(1, _TURNS - memory["turn"])
    blocked = {p for seat, p in positions.items() if seat != bot_id}
    root_dist, root_first = _paths(pos, blocked, legal)
    cache = {pos: (root_dist, root_first)}
    owned = sum(1 << i for i, c in enumerate(board) if c[0] == bot_id)
    upgraded = sum(1 << i for i, c in enumerate(board) if c[1])
    enemies = [(seat, p) for seat, p in positions.items() if seat != bot_id]
    enemy_distance = [min((abs(i // 8 - p // 8) + abs(i % 8 - p % 8)
                          for _, p in enemies), default=16) for i in range(64)]
    shield_ready = {seat: memory["turn"] - memory["shields"].get(seat, -10) > 4
                    for seat, _ in enemies}
    progress = memory["progress"].get(bot_id, 0)
    token = memory["token"]
    move_risk = {}
    for action, square in _NEIGHBORS[pos]:
        risk = 0.0
        if board[square][0] != bot_id:
            for seat, rival in enemies:
                if board[rival][3] or not any(p == square for _, p in _NEIGHBORS[rival]):
                    continue
                loses = (board[square][0] == seat or token is None
                         or (seat - token) % 4 < (bot_id - token) % 4)
                if loses:
                    p_move = 1.0 - _stay_probability(
                        board[rival], seat, memory["progress"].get(seat, 0))
                    risk += 0.65 * p_move
        move_risk[action] = min(0.9, risk)

    # Node: position, elapsed actions, owned mask, upgraded mask,
    # accumulated project value, first action, first target.
    beam = [(pos, 0, owned, upgraded, 0.0, None, pos)]
    best = None
    best_rating = -1.0
    for depth in range(4):
        expanded = []
        seen = set()
        for location, elapsed, own, levels, reward, first, first_target in beam:
            if perf_counter() >= deadline:
                if best:
                    memory["target"] = best[6]
                return (best[5], best_rating) if best else ("STAY", 0.0)
            if location not in cache:
                cache[location] = _paths(location, blocked)
            distances, actions = cache[location]
            candidates = []
            for square, cell in enumerate(board):
                bit = 1 << square
                is_ours = bool(own & bit)
                is_upgraded = bool(levels & bit)
                if (distances[square] == 99 or (cell[4] and cell[0] != bot_id)
                        or (is_ours and is_upgraded)):
                    continue
                stays = 3 if is_ours or is_upgraded else 1
                if depth == 0 and square == pos:
                    stays = max(1, stays - progress)
                cost = distances[square] + stays
                finish = elapsed + cost
                if finish > remaining:
                    continue
                action = first or actions[square]
                if action not in legal:
                    continue
                life = remaining - finish + 1
                value = cell[5]
                raid = 0
                denial = 0.0
                retention = 1.0
                if not is_ours and cell[0]:
                    previous_level = 2 if is_upgraded else 1
                    raid = 8 * value * previous_level
                    denial = 0.32 * value * previous_level * life
                    # The owner may shield even from far away. Treat the
                    # unknown decision as risk, never as a guaranteed action.
                    if shield_ready.get(cell[0], True):
                        retention *= 0.58 if is_upgraded else 0.70
                elif not is_ours:
                    # Central cells which both sides can reach are scarce.
                    if enemy_distance[square] <= distances[square] + 3:
                        denial = 0.12 * value * life
                if not cell[4]:
                    if is_ours:
                        # Armour protects the existing income as well as
                        # adding a second point stream.
                        denial += 0.45 * value * life
                    else:
                        retention *= min(1.0, 0.45 + enemy_distance[square] * 0.12)
                gain = (value * life + denial + raid) * retention
                if depth == 0:
                    gain *= 1.0 - 0.40 * move_risk.get(action, 0.0)
                # Tiny deterministic preference towards the valuable interior;
                # the actual map's base_points drive all substantial choices.
                central = 7 - abs(square // 8 - 3.5) - abs(square % 8 - 3.5)
                rating = gain / (cost + 0.8) + central * 0.12
                candidates.append((rating, gain, square, finish, action, is_ours))
            if not candidates:
                if first is not None:
                    rating = reward / (elapsed + 1.8)
                    expanded.append((rating, (location, elapsed, own, levels, reward, first, first_target)))
                continue
            candidates.sort(reverse=True)
            for _, gain, square, finish, action, is_ours in candidates[:8]:
                bit = 1 << square
                next_owned = own | bit
                next_levels = levels | bit if is_ours else levels & ~bit
                node = (square, finish, next_owned, next_levels,
                        reward + gain, action, first_target if first else square)
                key = (square, finish, next_owned, next_levels, action)
                if key in seen:
                    continue
                seen.add(key)
                rating = node[4] / (finish + 1.8)
                expanded.append((rating, node))
        if not expanded:
            break
        expanded.sort(key=lambda item: item[0], reverse=True)
        beam = [node for _, node in expanded[:12]]
        best_rating, best = expanded[0]
    if best:
        memory["target"] = best[6]
    return (best[5], best_rating) if best else ("STAY", 0.0)


def _profitable_detour(board, bot_id, pos, positions, memory, legal):
    """Take a safe extra capture when it cannot displace the final project.

    This narrow endgame case has a direct point comparison: capturing here
    adds value * remaining points and delays the destination income by one
    turn. Both cells must be neutral, and rivals must be too far away to
    interfere before we occupy the destination. No shield prediction is needed.
    """
    remaining = _TURNS - memory["turn"]
    target = memory.get("target")
    if (not 2 <= remaining <= 4 or target is None or target == pos
            or "STAY" not in legal or board[pos][0] or board[target][0]
            or board[pos][4] or board[target][4]):
        return False
    blocked = {p for seat, p in positions.items() if seat != bot_id}
    distances, _ = _paths(pos, blocked, legal)
    # The original project leaves exactly one otherwise unusable action.
    if distances[target] + 1 != remaining - 1:
        return False
    for seat, rival in positions.items():
        if seat == bot_id:
            continue
        for square in (pos, target):
            if abs(square // 8 - rival // 8) + abs(square % 8 - rival % 8) < remaining:
                return False
    return board[pos][5] * remaining > board[target][5]


def act(state):
    """Return one documented legal action without mutating state or doing I/O."""
    started = perf_counter()
    legal = tuple(state.legal_actions)
    fallback = "STAY" if "STAY" in legal else legal[0]
    board = _snapshot(state)
    memory, positions, pos = _observe(board, state.bot_id, legal, state.is_priority_token)
    if pos is None or len(board) != 64:
        memory["action"] = fallback
        return fallback
    if board[pos][3] or len(legal) == 1:
        memory["action"] = fallback
        return fallback
    # A bounded search plus a monotonic deadline leaves ample room beneath
    # the 200 ms competition limit, even on slower hosts.
    action, project_value = _plan(board, state.bot_id, pos, positions, memory,
                                  legal, started + 0.055)
    if "SHIELD" in legal:
        shield_value = _shield_value(board, state.bot_id, positions, memory,
                                     max(1, _TURNS - memory["turn"]))
        if shield_value > max(9.0, project_value * 0.82):
            action = "SHIELD"
    if action not in ("STAY", "SHIELD") and _profitable_detour(
            board, state.bot_id, pos, positions, memory, legal):
        action = "STAY"
    if action not in legal:
        action = fallback
    memory["action"] = action
    return action
