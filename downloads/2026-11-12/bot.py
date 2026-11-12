"""
StrategyBot - Zone Rush bot.

Single file, Python standard library only.  Entry point: act(state).

Layout of this file
  1. PARAMS          - every tunable weight / threshold in one place
  2. Snap            - reads `state` defensively into flat arrays (never mutates it)
  3. Memory          - per-game globals: turn counter, scores, progress, shields,
                       freezes, token order, rival behaviour statistics
  4. Tracker         - rebuilds the hidden information from consecutive snapshots
  5. Planner         - scores capture / raid / upgrade plans (2-step look-ahead)
  6. Shield logic    - expected value of SHIELD this turn
  7. act(state)      - safety shell: always returns a member of legal_actions

Board indexing follows the README: board[row][col], (0, 0) top-left,
NORTH = row - 1.  The bot verifies this from its own moves and adapts if the
server turns out to use a different orientation.
"""

import math
import os
import sys
import time

TOTAL_TURNS = 80
MOVES = ("NORTH", "EAST", "SOUTH", "WEST")
OPPOSITE = {"NORTH": "SOUTH", "SOUTH": "NORTH", "EAST": "WEST", "WEST": "EAST"}
README_DIRS = {"NORTH": (-1, 0), "SOUTH": (1, 0), "WEST": (0, -1), "EAST": (0, 1)}

# Plan kinds
NEUTRAL, RAID1, RAID2, UPGRADE = 0, 1, 2, 3

# ---------------------------------------------------------------------------
# 1. Parameters (tools/ may override them through PARAMS_OVERRIDE)
# ---------------------------------------------------------------------------
PARAMS = {
    # time budget per call (ms); the server allows 200 ms (2 s on turn 1)
    "budget_ms": 110.0,
    # Elo weighting of rivals
    "sigma_base": 30.0,
    "sigma_per_turn": 5.0,
    "w_uniform_mix": 0.35,
    # races for neutral cells
    "race_ahead": 0.55,
    "race_tie_lose": 0.35,
    "race_tie_win": 0.05,
    "race_value_scale": 0.5,
    # raids
    "rho_prior": 0.45,          # P(owner shields | a rival stays on its land)
    "rho_prior_n": 2.0,         # strength of that prior (pseudo-observations)
    "raid_caught_delay": 3.0,   # turns lost when a raid is shielded
    "raid2_caught_delay": 3.0,
    "bait_value": 25.0,         # value of making a shield-happy owner backfire
    # upgrades
    "upg_def_frac": 0.0,        # extra defence value of upgrading a cell near rivals (x v*G)
    "upg_def_radius": 4,
    # cell durability: learned per-turn raid hazard for level-1 / level-2 cells
    "lam1_prior": 0.045,        # tuned: 0.01 << 0.02 < 0.03 < 0.045 ~ 0.06
    "lam2_prior": 0.004,
    "lam2_prior_fz": 0.012,     # when frozen stays build progress, shields defend L2 poorly
    # Once the frozen-progress rule is detected, only the raid valuation switches
    # to its fz form. Switching the L2 hazard and the shield value too was measured
    # worse (runs/improve_log.md, E3/E5), so both are off.
    "fz_hazard": False,
    "fz_shield": False,
    "lam_prior_n": 300.0,       # prior strength in cell-turns
    "use_life": True,
    "expo_k": 0.0,              # hazard multiplier slope by distance to nearest rival bot
    "expo_r": 2.5,
    # shield decision
    "q_prior": 0.55,            # P(rival standing on my cell stays this turn)
    "q_prior_n": 2.0,
    "q_committed": 0.85,        # P(stay) once it has already stayed on my L2 cell
    "shield_giveup": 0.25,      # chance a frozen L1 raider gives up afterwards
    "shield_recatch": 0.9,      # chance we can catch an L2 raider again later
    "shield_early_frac": 0.5,   # value of catching an L2 raider before its last stay
    "rival_rate": 14.0,         # value per turn of a rival's time (for freezes)
    "backfire_turns": 2.0,
    "cooldown_cost": 6.0,
    "shield_margin": 0.0,
    # planning
    "chain_top": 14,
    "chain_top2": 6,
    "chain_depth": 2,           # plans per chain (1 = greedy rate); 3 tested worse
    "hysteresis": 0.10,
    "contest_block_p": 0.3,     # P(an adjacent rival moves into the same cell)
    "home_upgrade": False,      # never plan to upgrade the home cell
}
PARAMS_OVERRIDE = {}
P = dict(PARAMS)
P.update(PARAMS_OVERRIDE)

_DEBUG = bool(os.environ.get("ZR_DEBUG"))
_MEM = None


# ---------------------------------------------------------------------------
# 2. Snapshot of the state
# ---------------------------------------------------------------------------
def _attr(obj, name, default):
    try:
        v = getattr(obj, name)
    except Exception:
        return default
    return default if v is None else v


class Snap(object):
    """Flat, read-only copy of everything the bot needs from `state`."""

    def __init__(self, state):
        board = state.board
        first = board[0]
        if hasattr(first, "owner") or hasattr(first, "occupant"):
            cells = list(board)                       # flat list of 64
        else:
            cells = [c for row in board for c in row]  # 8 x 8 list of lists
        size = len(cells)
        n = int(round(math.sqrt(size)))
        self.n = n
        self.size = size
        self.occ = [int(_attr(c, "occupant", 0)) for c in cells]
        self.own = [int(_attr(c, "owner", 0)) for c in cells]
        self.lvl = [2 if _attr(c, "is_upgraded", False) else 1 for c in cells]
        self.home = [bool(_attr(c, "is_home", False)) for c in cells]
        self.frz = [bool(_attr(c, "is_frozen", False)) for c in cells]
        self.val = [int(_attr(c, "base_points", 1)) for c in cells]
        self.pos = {}
        for i, b in enumerate(self.occ):
            if b:
                self.pos[b] = i
        self.me = int(state.bot_id)
        self.token = bool(_attr(state, "is_priority_token", False))
        raw = list(_attr(state, "legal_actions", ["STAY"])) or ["STAY"]
        self.legal_map = {}
        for a in raw:
            self.legal_map.setdefault(str(a).strip().upper(), a)
        self.legal = set(self.legal_map)
        self.homes = {}
        for i in range(size):
            if self.home[i] and self.own[i]:
                self.homes[self.own[i]] = i
        self.bots = sorted(self.pos)

    def frozen(self, b):
        p = self.pos.get(b)
        return p is not None and self.frz[p]


# ---------------------------------------------------------------------------
# 3. Per-game memory (globals)
# ---------------------------------------------------------------------------
class Memory(object):
    def __init__(self, snap):
        self.n = snap.n
        self.val = tuple(snap.val)
        self.me = snap.me
        self.turn = 0
        self.prev = None
        self.last_action = None
        self.last_shield_legal = False
        ids = set(snap.bots) | {1, 2, 3, 4}
        self.ids = sorted(ids)
        self.scores = dict((b, 0.0) for b in ids)
        self.prog = dict((b, 0) for b in ids)
        self.frz_run = dict((b, 0) for b in ids)
        self.last_shield = dict((b, -100) for b in ids)
        self.stats = dict((b, {"opp": 0, "sh": 0, "spam": 0, "rv_opp": 0, "rv_stay": 0, "urgent_opp": 0, "urgent_sh": 0}) for b in ids)
        self.tok_k = {0, 1, 2, 3}
        self.homes = dict(snap.homes)
        for b, p in snap.pos.items():          # fallback: start cell = home
            if b not in self.homes:
                self.homes[b] = p
        self.dmap = dict(README_DIRS)
        self.target = None
        self.raid_interrupts = {}  # (owner, cell) -> confirmed interrupted L2 raids
        # Compatibility flag: the official rules never count frozen stays.
        self.fz_prog = False
        self.frz_seen_on_cell = {}
        # raid hazard bookkeeping: index = level (1 or 2)
        self.cellturns = [0, 0, 0]
        self.raids = [0, 0, 0]
        self.my_cellturns = [0, 0, 0]
        self.my_raids = [0, 0, 0]
        self.inferred = []                       # debug: shields inferred last update


def _manh(n, a, b):
    ar, ac = divmod(a, n)
    br, bc = divmod(b, n)
    return abs(ar - br) + abs(ac - bc)


def _is_new_game(mem, snap):
    if mem is None:
        return True
    if mem.me != snap.me or mem.n != snap.n:
        return True
    if mem.turn >= TOTAL_TURNS and _is_start(snap):
        return True
    if mem.val != tuple(snap.val):
        return True
    prev = mem.prev
    if prev is None:
        return False
    for i in range(snap.size):                 # ownership never reverts to neutral
        if prev.own[i] and not snap.own[i]:
            return True
    return False


def _is_start(snap):
    """Start-of-game board: only homes are owned and every bot is on a home."""
    for i in range(snap.size):
        if snap.own[i] and not snap.home[i]:
            return False
    return all(snap.home[p] for p in snap.pos.values())


def _skipped_turns(mem, snap):
    """Bots move at most one cell a turn: a bigger jump means we were not
    called on some turns. Returns how many extra turns passed (usually 0)."""
    prev = mem.prev
    if prev is None:
        return 0
    jump = 0
    for b, p in snap.pos.items():
        q = prev.pos.get(b)
        if q is not None:
            jump = max(jump, _manh(snap.n, p, q))
    return max(0, jump - 1)


# ---------------------------------------------------------------------------
# 4. Tracker
# ---------------------------------------------------------------------------
def _learn_dirs(mem, prev, cur, action):
    """Check the README direction table against our own observed move."""
    if action not in MOVES:
        return
    a, b = prev.pos.get(mem.me), cur.pos.get(mem.me)
    if a is None or b is None or a == b:
        return
    n = mem.n
    ar, ac = divmod(a, n)
    br, bc = divmod(b, n)
    d = (br - ar, bc - ac)
    if abs(d[0]) + abs(d[1]) != 1 or d == mem.dmap[action]:
        return
    old = mem.dmap[action]
    mem.dmap[action] = d
    mem.dmap[OPPOSITE[action]] = (-d[0], -d[1])
    if (old[0] == 0) != (d[0] == 0):            # axis changed -> transpose the other pair
        for other in MOVES:
            if other != action and other != OPPOSITE[action]:
                r, c = mem.dmap[other]
                mem.dmap[other] = (c, r)


def _token_update(mem, t, me, has_token):
    ks = set(k for k in mem.tok_k if ((((t - 1 + k) % 4) + 1) == me) == has_token)
    if not ks:
        ks = set(k for k in range(4) if ((((t - 1 + k) % 4) + 1) == me) == has_token)
    mem.tok_k = ks


def _holder(mem, u):
    k = 0 if 0 in mem.tok_k else min(mem.tok_k)
    return ((u - 1 + k) % 4) + 1


def _first_in_order(mem, u, a, b):
    """True if seat a comes before seat b in priority order on turn u."""
    h = _holder(mem, u)
    return ((a - h) % 4) < ((b - h) % 4)


def _update(mem, prev, cur):
    """Fold the turn that just resolved (prev -> cur) into memory."""
    t = mem.turn - 1
    me = mem.me
    bots = [b for b in cur.bots if b in prev.pos]
    moved = dict((b, prev.pos[b] != cur.pos[b]) for b in bots)
    was_frz = dict((b, prev.frozen(b)) for b in bots)
    newly = {}
    for b in bots:
        if cur.frozen(b):
            if was_frz[b] and mem.frz_run[b] < 2:
                mem.frz_run[b] += 1
                newly[b] = False
            else:
                mem.frz_run[b] = 1
                newly[b] = not was_frz[b]
        else:
            mem.frz_run[b] = 0
            newly[b] = False

    # --- attributable shields only ---
    # A freeze on a rival's land is ambiguous: its owner may have shielded,
    # or the visitor's own shield may have backfired. Our known action and
    # neutral/own territory can resolve some cases; do not invent cooldowns.
    shielders = set()
    ambiguous = set()
    our_shield = mem.last_action == "SHIELD" and mem.last_shield_legal
    if our_shield:
        shielders.add(me)
    for b in bots:
        if not newly[b] or moved[b]:
            continue
        owner = prev.own[cur.pos[b]]
        if b == me:
            source = me if our_shield else (owner if owner and owner != me else None)
        elif owner == me:
            source = me if our_shield else b
        elif not owner or owner == b:
            source = b
        elif was_frz.get(owner, False) or t <= mem.last_shield.get(owner, -100) + 4:
            source = b
        else:
            source = None
            ambiguous.update((b, owner))
        if source is not None:
            shielders.add(source)
    mem.inferred = sorted(shielders)
    # One confirmed interruption is enough to identify the 3-stay / 2-freeze /
    # 4-cooldown lock. Do not learn a false "safe" signal from its early stays.
    if me in bots and newly.get(me) and not moved[me] and not our_shield:
        x = cur.pos[me]
        owner = prev.own[x]
        if owner not in (0, me) and prev.lvl[x] == 2 and owner in shielders:
            key = (owner, x)
            mem.raid_interrupts[key] = mem.raid_interrupts.get(key, 0) + 1

    # --- behaviour statistics (before last_shield is updated) ---
    for o in bots:
        if (was_frz[o] or t <= mem.last_shield[o] + 4
                or (o in ambiguous and o not in shielders)):
            continue
        intruders = [b for b in bots if b != o and prev.own[prev.pos[b]] == o and not was_frz[b]]
        st = mem.stats[o]
        if intruders:
            st["opp"] += 1
            if o in shielders:
                st["sh"] += 1
            # Patient defenders shield only on the completing stay. Mixing
            # those opportunities with harmless earlier stays understates risk.
            urgent = any(not prev.home[prev.pos[b]] and
                         (prev.lvl[prev.pos[b]] == 1 or mem.prog.get(b, 0) >= 2)
                         for b in intruders)
            if urgent:
                st["urgent_opp"] += 1
                if o in shielders:
                    st["urgent_sh"] += 1
        elif o in shielders:
            st["spam"] += 1
    for b in bots:
        x = prev.pos[b]
        o = prev.own[x]
        if (o and o != b and not prev.home[x] and not was_frz[b]
                and b not in ambiguous):
            st = mem.stats[b]
            st["rv_opp"] += 1
            if not moved[b] and b not in shielders:
                st["rv_stay"] += 1

    for s in shielders:
        mem.last_shield[s] = t

    # The official rulebook is explicit: frozen turns reset progress and
    # never build it. Keep this compatibility flag false, even if an
    # inconsistent snapshot would otherwise look like a completed action.
    mem.fz_prog = False

    # --- progress (consecutive effective stays on the current cell) ---
    for b in bots:
        x = cur.pos[b]
        if moved[b] or b in shielders or newly[b] or was_frz[b]:
            mem.prog[b] = 0
            continue
        mem.prog[b] += 1
        if prev.own[x] != b and cur.own[x] == b:
            mem.prog[b] = 0                       # take completed
        elif prev.own[x] == b and prev.lvl[x] == 1 and cur.lvl[x] == 2:
            mem.prog[b] = 0                       # upgrade completed
        elif cur.own[x] != b and prev.own[x] != cur.own[x]:
            mem.prog[b] = 0                       # owner changed under us
        elif (cur.own[x] == b and cur.lvl[x] == 2) or (cur.home[x] and cur.own[x] != b):
            mem.prog[b] = 0                       # no work remains / forbidden home
        elif mem.prog[b] >= (3 if cur.own[x] == b or cur.lvl[x] == 2 else 1):
            mem.prog[b] = 0                       # expected completion absent

    # --- raid hazard: owned non-home cell-turns and how many got raided ---
    for i in range(cur.size):
        po = prev.own[i]
        if po and not prev.home[i]:
            lv = prev.lvl[i]
            mem.cellturns[lv] += 1
            raided = cur.own[i] and cur.own[i] != po
            if raided:
                mem.raids[lv] += 1
            if po == me:
                mem.my_cellturns[lv] += 1
                if raided:
                    mem.my_raids[lv] += 1

    # --- scores: income at end of turn t + raid bonuses ---
    for i in range(cur.size):
        o = cur.own[i]
        if o:
            mem.scores[o] = mem.scores.get(o, 0.0) + cur.val[i] * cur.lvl[i]
            po = prev.own[i]
            if po and po != o:
                mem.scores[o] += 8 * cur.val[i] * prev.lvl[i]

    if mem.last_action in MOVES:
        _learn_dirs(mem, prev, cur, mem.last_action)


# ---------------------------------------------------------------------------
# 5. Planner
# ---------------------------------------------------------------------------
class Ctx(object):
    pass


def _neighbors(mem, idx):
    n = mem.n
    r, c = divmod(idx, n)
    out = []
    for a in MOVES:
        dr, dc = mem.dmap[a]
        rr, cc = r + dr, c + dc
        if 0 <= rr < n and 0 <= cc < n:
            out.append((a, rr * n + cc))
    return out


def _bfs(mem, start, blocked):
    dist = [-1] * (mem.n * mem.n)
    dist[start] = 0
    q = [start]
    for x in q:
        dx = dist[x] + 1
        for _, y in _neighbors(mem, x):
            if dist[y] < 0 and not blocked[y]:
                dist[y] = dx
                q.append(y)
    return dist


def _rho(mem, o):
    st = mem.stats.get(o)
    if st is None:
        return P["rho_prior"]
    n0 = P["rho_prior_n"]
    return (st["sh"] + P["rho_prior"] * n0) / (st["opp"] + n0)


def _rho_urgent(mem, owner):
    st = mem.stats.get(owner, {})
    return (st.get("urgent_sh", 0) + 1.3) / (st.get("urgent_opp", 0) + 2.0)


def _q_stay(mem, r):
    st = mem.stats.get(r)
    n0 = P["q_prior_n"]
    if st is None:
        return P["q_prior"]
    return (st["rv_stay"] + P["q_prior"] * n0) / (st["rv_opp"] + n0)


def _build_ctx(mem, snap):
    c = Ctx()
    c.mem, c.s = mem, snap
    c.t = mem.turn
    c.R = max(1, TOTAL_TURNS - c.t + 1)
    c.me = mem.me
    c.rivals = [b for b in snap.bots if b != c.me]
    c.mypos = snap.pos[c.me]
    size = snap.size

    # frozen_until[b]: last turn on which b is still frozen (t-1 if not frozen)
    c.frozen_until = {}
    for b in snap.bots:
        if snap.frozen(b):
            run = max(1, mem.frz_run.get(b, 1))
            c.frozen_until[b] = c.t + max(0, 2 - run)
        else:
            c.frozen_until[b] = c.t - 1

    # distances (cells occupied by other bots are closed)
    occ = [False] * size
    for b, p in snap.pos.items():
        occ[p] = True
    blocked = list(occ)
    blocked[c.mypos] = False
    c.dme = _bfs(mem, c.mypos, blocked)
    c.dr = {}
    for b in c.rivals:
        bl = list(occ)
        bl[snap.pos[b]] = False
        d = _bfs(mem, snap.pos[b], bl)
        extra = max(0, c.frozen_until[b] - c.t + 1)
        if extra:
            d = [x + extra if x >= 0 else x for x in d]
        c.dr[b] = d

    # income + Elo weights
    income = dict((b, 0) for b in mem.ids)
    for i in range(size):
        o = snap.own[i]
        if o:
            income[o] = income.get(o, 0) + snap.val[i] * snap.lvl[i]
    c.income = income
    proj = dict((b, mem.scores.get(b, 0.0) + income.get(b, 0) * c.R) for b in snap.bots)
    c.proj = proj
    sigma = P["sigma_base"] + P["sigma_per_turn"] * c.R
    sens = {}
    for r in c.rivals:
        z = (proj[c.me] - proj[r]) / sigma
        z = max(-30.0, min(30.0, z))
        p = 1.0 / (1.0 + math.exp(-z))
        sens[r] = p * (1.0 - p)
    tot = sum(sens.values())
    mix = P["w_uniform_mix"]
    nr = max(1, len(c.rivals))
    c.w = {}
    for r in c.rivals:
        base = sens[r] / tot if tot > 1e-12 else 1.0 / nr
        c.w[r] = (1.0 - mix) * base + mix / nr
    c.w[0] = 0.0
    c.rho = dict((r, _rho(mem, r)) for r in c.rivals)
    n0 = P["lam_prior_n"]
    c.lam1 = (mem.raids[1] + P["lam1_prior"] * n0) / (mem.cellturns[1] + n0)
    c.lam2 = (mem.raids[2] + P["lam2_prior"] * n0) / (mem.cellturns[2] + n0)
    fz_haz = mem.fz_prog and P["fz_hazard"]
    lam2_prior = P["lam2_prior_fz"] if fz_haz else P["lam2_prior"]
    c.lam2_mine = (mem.my_raids[2] + lam2_prior * n0) / (mem.my_cellturns[2] + n0)
    if fz_haz:
        c.lam2 = max(c.lam2, c.lam2_mine)
    c.w_avg = 1.0 / nr
    # exposure: cells near a rival bot get raided sooner
    k, r0 = P["expo_k"], P["expo_r"]
    c.expo = [1.0] * size
    if k:
        for x in range(size):
            md = 99
            for b in c.rivals:
                d = c.dr[b][x]
                if 0 <= d < md:
                    md = d
            c.expo[x] = min(3.0, max(0.3, 1.0 + k * (r0 - md) / r0))
    return c


def _life(G, lam):
    """Expected number of scoring turns over G turns for a cell raided at rate lam."""
    if G <= 0:
        return 0.0
    if not P["use_life"] or lam <= 1e-9:
        return float(G)
    return (1.0 - (1.0 - lam) ** G) / lam


def _shield_avail(c, o, u):
    mem = c.mem
    return u > mem.last_shield.get(o, -100) + 4 and u > c.frozen_until.get(o, c.t - 1)


def _raid_locked(c, x, kind, d, prog, start_turn, own):
    """A known defender must be unable to shield for every remaining stay.

    Escaping one cell and attacking another upgraded cell of the same owner
    does not solve the lock, so the evidence applies to that owner's territory.
    A newly observed cooldown can reopen a capture window; movement consumes
    that window too. All timing uses actual rules, not a discounted reward.
    """
    if kind != RAID2:
        return False
    owner = own[x]
    if not any(o == owner for o, _ in c.mem.raid_interrupts):
        return False
    stays = max(1, 3 - prog)
    return any(_shield_avail(c, owner, u)
               for u in range(start_turn + d, start_turn + d + stays))


def _escape(c):
    candidates = []
    for action, square in _neighbors(c.mem, c.mypos):
        if action not in c.s.legal or c.s.occ[square]:
            continue
        owner = c.s.own[square]
        category = 4 if not owner else 3 if owner == c.me else 1 if c.s.lvl[square] == 1 else 0
        candidates.append((category, c.s.val[square], action))
    return max(candidates)[2] if candidates else None


def _kind_of(c, x, own, lvl):
    """Plan kind for cell x given an ownership view, or None."""
    s = c.s
    o = own[x]
    if o == c.me:
        if lvl[x] == 1 and (not s.home[x] or P["home_upgrade"]):
            return UPGRADE
        return None
    if s.home[x]:
        return None
    if o == 0:
        return NEUTRAL
    return RAID1 if lvl[x] == 1 else RAID2


def _stays_needed(kind):
    return 1 if kind in (NEUTRAL, RAID1) else 3


def _race_keep(c, x, d, arrival_turn):
    """Probability we, not a rival, end up taking neutral cell x."""
    if d <= 0:
        return 1.0
    v = c.s.val[x]
    scale = P["race_value_scale"] + (1.0 - P["race_value_scale"]) * v / 3.0
    keep = 1.0
    for b in c.rivals:
        db = c.dr[b][x]
        if db < 0:
            continue
        if db < d:
            p = P["race_ahead"]
        elif db == d:
            p = P["race_tie_win"] if _first_in_order(c.mem, arrival_turn, c.me, b) else P["race_tie_lose"]
        else:
            continue
        keep *= 1.0 - p * scale
    return keep


def _evaluate(c, x, kind, d, prog, start_turn, own, lvl, timed=True):
    """Return (utility, turns) for doing `kind` on cell x, d moves away,
    starting at absolute turn start_turn with `prog` stays already done."""
    s = c.s
    v = s.val[x]
    o = own[x]
    stays = max(1, _stays_needed(kind) - prog)
    k = d + stays
    R = TOTAL_TURNS - start_turn + 1
    if k > R:
        return None
    if _raid_locked(c, x, kind, d, prog, start_turn, own):
        return None
    keep = 1.0
    delay = 0.0
    if kind == NEUTRAL:
        keep = _race_keep(c, x, d + (start_turn - c.t), start_turn + d - 1)
    elif kind in (RAID1, RAID2):
        rho = c.rho.get(o, P["rho_prior"])
        if timed:
            n_av = 0
            for u in range(start_turn + d, start_turn + d + stays):
                if _shield_avail(c, o, u):
                    n_av += 1
        else:
            n_av = stays
        survives = 1.0
        for offset in range(stays):
            u = start_turn + d + offset
            if not timed or _shield_avail(c, o, u):
                urgent = kind == RAID1 or prog + offset >= 2
                chance = _rho_urgent(c.mem, o) if urgent else rho
                survives *= 1.0 - chance
        pc = 1.0 - survives
        if c.mem.fz_prog:
            # frozen stays still count: a catch only costs the protected stay
            delay = (1.0 if kind == RAID1 else 2.0) * pc
        elif kind == RAID1:
            delay = P["raid_caught_delay"] * pc
        else:
            keep = 1.0 - pc
            delay = P["raid2_caught_delay"] * pc
    k_eff = k + delay
    G = R - k_eff + 1
    if G <= 0:
        return None
    w = c.w.get(o, 0.0)
    life1 = _life(G, c.lam1 * c.expo[x])
    if kind == NEUTRAL:
        u = v * life1
    elif kind == RAID1:
        u = 8 * v + v * life1 + w * v * life1
    elif kind == RAID2:
        u = 16 * v + v * life1 + w * 2 * v * _life(G, c.lam2)
    else:
        # level 2 lasts longer (we defend it with shields) and denies raid bonuses
        u = 2 * v * _life(G, c.lam2_mine) - v * life1
        if P["use_life"]:
            u += c.w_avg * 8 * v * (1.0 - (1.0 - c.lam1) ** G)
        rad = P["upg_def_radius"]
        md = min([c.dr[b][x] for b in c.rivals if c.dr[b][x] >= 0] or [99])
        if md <= rad:
            u += P["upg_def_frac"] * v * G * (rad + 1 - md) / (rad + 1.0)
    return u * keep, k_eff


def _apply(c, own, lvl, x, kind):
    own2 = list(own)
    lvl2 = list(lvl)
    if kind == UPGRADE:
        lvl2[x] = 2
    else:
        own2[x] = c.me
        lvl2[x] = 1
    return own2, lvl2


def _chain(c, x, kind, u_acc, k_acc, own, lvl, t0, depth, deadline):
    """Best rate (total utility / total turns) of chains that start with the
    given (already accumulated) plans and continue up to `depth` more plans."""
    s = c.s
    n = s.n
    own2, lvl2 = _apply(c, own, lvl, x, kind)
    t2 = t0 + int(math.ceil(k_acc))
    if t2 > TOTAL_TURNS:
        return u_acc / k_acc
    best = u_acc / k_acc
    nxt = []
    for y in range(s.size):
        kind2 = _kind_of(c, y, own2, lvl2)
        if kind2 is None:
            continue
        if y != x and s.occ[y] and y != c.mypos:
            continue
        d2 = 0 if y == x else _manh(n, x, y)
        ev2 = _evaluate(c, y, kind2, d2, 0, t2, own2, lvl2, timed=False)
        if ev2 is None:
            continue
        u2, k2 = ev2
        r2 = (u_acc + u2) / (k_acc + k2)
        if r2 > best:
            best = r2
        nxt.append((r2, u2, k2, y, kind2))
    if depth > 1 and nxt and time.perf_counter() < deadline:
        nxt.sort(reverse=True)
        for r2, u2, k2, y, kind2 in nxt[:int(P["chain_top2"])]:
            r3 = _chain(c, y, kind2, u_acc + u2, k_acc + k2, own2, lvl2, t0, depth - 1, deadline)
            if r3 > best:
                best = r3
    return best


def _endgame_plan(c, first, deadline):
    """Bounded rolling-horizon project search, maximizing remaining utility.

    Inspired by rolling-horizon planning (Liu et al., arXiv:1607.01730),
    adapted as a deterministic beam rather than evolutionary search. Replans
    each turn; paths respect current occupancy. No model training or libraries.
    """
    blocked = [bool(v) for v in c.s.occ]
    blocked[c.mypos] = False
    distances = {c.mypos: c.dme}
    best = {}
    beam = []
    # A node stores achieved utility, elapsed turns, position, changed board,
    # first project. Its utility already includes income through turn 80.
    for _, u, k, x, kind in first:
        own, lvl = _apply(c, c.s.own, c.s.lvl, x, kind)
        root = (x, kind, u, k)
        best[(x, kind)] = (u, root)
        beam.append((u, int(math.ceil(k)), x, own, lvl, root))
    beam.sort(key=lambda node: node[0], reverse=True)
    beam = beam[:24]
    evaluations = 0
    for _ in range(min(6, c.R - 1)):
        nxt = []
        for total, elapsed, x, own, lvl, root in beam:
            if elapsed >= c.R or evaluations >= 4000 or time.perf_counter() >= deadline:
                continue
            if x not in distances:
                distances[x] = _bfs(c.mem, x, blocked)
            ds = distances[x]
            for y, d in enumerate(ds):
                if d < 0 or blocked[y]:
                    continue
                kind = _kind_of(c, y, own, lvl)
                if kind is None or d + _stays_needed(kind) > c.R - elapsed:
                    continue
                evaluations += 1
                ev = _evaluate(c, y, kind, d, 0, c.t + elapsed, own, lvl, timed=True)
                if ev is None or ev[0] <= 0:
                    continue
                u, k = ev
                duration = elapsed + int(math.ceil(k))
                if duration > c.R:
                    continue
                value = total + u
                key = root[:2]
                if value > best[key][0]:
                    best[key] = (value, root)
                own2, lvl2 = _apply(c, own, lvl, y, kind)
                nxt.append((value, duration, y, own2, lvl2, root))
            if evaluations >= 4000:
                break
        if not nxt or evaluations >= 4000 or time.perf_counter() >= deadline:
            break
        nxt.sort(key=lambda node: node[0], reverse=True)
        beam = nxt[:24]
    ranked = [(value, x, kind, u, k) for value, (x, kind, u, k) in best.values()]
    ranked.sort(key=lambda row: row[0], reverse=True)
    return ranked


def _plan(c, deadline):
    s, mem = c.s, c.mem
    own, lvl = s.own, s.lvl
    me = c.me
    first = []
    for x in range(s.size):
        if x == c.mypos:
            kind = _kind_of(c, x, own, lvl)
            if kind is None:
                continue
            ev = _evaluate(c, x, kind, 0, mem.prog.get(me, 0), c.t, own, lvl)
        else:
            d = c.dme[x]
            if d < 0 or s.occ[x]:
                continue
            kind = _kind_of(c, x, own, lvl)
            if kind is None:
                continue
            ev = _evaluate(c, x, kind, d, 0, c.t, own, lvl)
        if ev is None:
            continue
        u, k = ev
        if u <= 0:
            continue
        first.append((u / k, u, k, x, kind))
    if not first:
        return None
    first.sort(reverse=True)
    if c.R <= 12:
        return _endgame_plan(c, first, deadline)

    # bait: moving off a shield-ready owner's land can make it backfire
    here_owner = own[c.mypos]
    bait = 0.0
    if here_owner and here_owner != me and _shield_avail(c, here_owner, c.t):
        bait = c.rho.get(here_owner, P["rho_prior"]) * P["bait_value"] * c.w.get(here_owner, 0.0) * 3.0

    ranked = []
    top = first[:int(P["chain_top"])]
    for rate, u1, k1, x, kind in top:
        score = rate
        if time.perf_counter() < deadline:
            if P["chain_depth"] > 1:
                score = max(score, _chain(c, x, kind, u1, k1, own, lvl, c.t,
                                          int(P["chain_depth"]) - 1, deadline))
        if x != c.mypos:
            score += bait / max(1.0, k1)
        if mem.target is not None and mem.target == (x, kind):
            score *= 1.0 + P["hysteresis"]
        ranked.append((score, x, kind, u1, k1))
    ranked.sort(key=lambda p: p[0], reverse=True)
    return ranked


def _step_toward(c, target):
    """First move on a shortest path to target, avoiding contests we'd lose."""
    s, mem, me = c.s, c.mem, c.me
    occ = [False] * s.size
    for b, p in s.pos.items():
        occ[p] = True
    bl = list(occ)
    bl[c.mypos] = False
    bl[target] = False
    dt = _bfs(mem, target, bl)
    here = dt[c.mypos]
    best = None
    for a, y in _neighbors(mem, c.mypos):
        if a not in s.legal or occ[y]:
            continue
        if dt[y] < 0 or (here >= 0 and dt[y] >= here):
            continue
        risk = 0.0
        for b in c.rivals:
            if c.frozen_until[b] >= c.t:
                continue
            pb = s.pos[b]
            if _manh(s.n, pb, y) != 1:
                continue
            if s.own[y] == me:
                continue
            if s.own[y] == b or not _first_in_order(mem, c.t, me, b):
                risk += P["contest_block_p"]
        score = -risk + 0.01 * s.val[y] + (0.02 if s.own[y] != me else 0.0)
        if best is None or score > best[0]:
            best = (score, a)
    return best[1] if best else None


# ---------------------------------------------------------------------------
# 6. Shield decision
# ---------------------------------------------------------------------------
def _shield_value(c, plan):
    s, mem = c.s, c.mem
    if "SHIELD" not in s.legal:
        return None
    me = c.me
    # what one turn of our own plan is worth, and what shielding throws away
    my_prog = mem.prog.get(me, 0)
    if plan is None:
        my_rate, lost_turns = 0.0, 1.0
    else:
        u1, k1 = plan[3], plan[4]
        if plan[1] == c.mypos:
            my_rate = u1 / max(1.0, k1 + my_prog)
            lost_turns = 1.0 + my_prog
        else:
            my_rate = u1 / max(1.0, k1)
            lost_turns = 1.0
    ev = 0.0
    p_none = 1.0
    any_threat = False
    for r in c.rivals:
        if c.frozen_until[r] >= c.t:
            continue                     # already frozen: can't be caught
        x = s.pos[r]
        if s.own[x] != me:
            continue
        v = s.val[x]
        G = c.R
        w = c.w.get(r, 0.0)
        prog = mem.prog.get(r, 0)
        needed = max(1, (3 if s.lvl[x] == 2 else 1) - prog)
        if (s.home[x] and G == 1) or (not s.home[x] and needed > G):
            continue
        any_threat = True
        if s.home[x]:
            q = _q_stay(mem, r) * 0.5
            saved = 0.0
        elif s.lvl[x] == 1:
            q = _q_stay(mem, r)
            full = v * G + w * (8 * v + v * G)
            saved = 3 * v + P["shield_giveup"] * full
        else:
            full = 2 * v * G + w * (16 * v + v * G)
            if prog >= 2:
                q = max(_q_stay(mem, r), P["q_committed"])
                saved = P["shield_recatch"] * full
            elif prog >= 1:
                q = max(_q_stay(mem, r), P["q_committed"])
                saved = P["shield_early_frac"] * full
            else:
                q = _q_stay(mem, r)
                saved = 0.25 * P["shield_early_frac"] * full
        if G <= 3 and not s.home[x]:
            # A catch covers the rest of the game. Count income only from
            # the turn the unblocked raid would actually complete.
            lost_income_turns = G - needed + 1
            saved = v * s.lvl[x] * lost_income_turns
            saved += w * (8 * v * s.lvl[x] + v * lost_income_turns)
        freeze = w * min(3.0, float(G)) * P["rival_rate"] if G > 1 else 0.0
        if mem.fz_prog and P["fz_shield"] and not s.home[x]:
            # a caught raider keeps building progress while frozen: we only
            # delay the take by the protected turn(s)
            saved = v * s.lvl[x] * (1.0 if s.lvl[x] == 1 else 3.0)
            freeze = w * P["rival_rate"]
        ev += q * (saved + freeze)
        p_none *= 1.0 - q
    if not any_threat:
        return None
    cost = my_rate * lost_turns
    cost += p_none * min(P["backfire_turns"], max(0, c.R - 1)) * my_rate
    cost += P["cooldown_cost"] * min(1.0, max(0, c.R - 1) / 4.0)
    return ev - cost - P["shield_margin"]


# ---------------------------------------------------------------------------
# 7. Entry point
# ---------------------------------------------------------------------------
def _log_exc():
    if _DEBUG:
        import traceback
        traceback.print_exc(file=sys.stderr)


def _choose(state, t0):
    global _MEM
    snap = Snap(state)
    if _is_new_game(_MEM, snap):
        _MEM = Memory(snap)
    mem = _MEM
    mem.turn += 1
    try:
        mem.turn = min(TOTAL_TURNS, mem.turn + _skipped_turns(mem, snap))
    except Exception:
        _log_exc()
    try:
        if mem.prev is not None:
            _update(mem, mem.prev, snap)
        _token_update(mem, mem.turn, snap.me, snap.token)
        for b, h in snap.homes.items():
            mem.homes[b] = h
    except Exception:
        _log_exc()

    action = "STAY"
    try:
        action = _decide(mem, snap, t0)
    except Exception:
        _log_exc()
        action = "STAY"
    if action not in snap.legal:
        action = "STAY"
    mem.prev = snap
    mem.last_action = action
    mem.last_shield_legal = "SHIELD" in snap.legal
    return snap.legal_map.get(action, snap.legal_map.get("STAY", "STAY"))


def _decide(mem, snap, t0):
    action = "STAY"
    if snap.me in snap.pos and len(snap.legal) > 1:
        budget = P["budget_ms"] / 1000.0
        deadline = t0 + budget * 0.8
        c = _build_ctx(mem, snap)
        ranked = _plan(c, deadline) or []
        plan = None
        step = None
        for cand in ranked:                     # best plan we can actually start
            if cand[1] == c.mypos:
                plan, step = cand, "STAY"
                break
            st = _step_toward(c, cand[1])
            if st:
                plan, step = cand, st
                break
        sv = _shield_value(c, plan)
        if sv is not None and sv > 0:
            action = "SHIELD"
            mem.target = None
        elif plan is not None:
            mem.target = (plan[1], plan[2])
            action = step
        if action == "STAY" and _raid_locked(c, c.mypos, _kind_of(c, c.mypos, snap.own, snap.lvl),
                                              0, mem.prog.get(c.me, 0), c.t, snap.own):
            action = _escape(c) or action
            mem.target = None
        if _DEBUG:
            sys.stderr.write("ZRDBG %s\n" % repr({
                "turn": mem.turn, "me": mem.me, "act": action, "plan": plan and plan[1:3],
                "shield_ev": sv, "scores": dict(mem.scores), "prog": dict(mem.prog),
                "last_shield": dict(mem.last_shield), "inferred": mem.inferred,
                "rho": c.rho, "w": c.w}))
    return action


def act(state): # Do not change or modify this function signature
    t0 = time.perf_counter()
    try:
        return _choose(state, t0)
    except Exception:
        _log_exc()
        try:
            legal = list(state.legal_actions)
            for a in legal:
                if str(a).upper() == "STAY":
                    return a
            return legal[0]
        except Exception:
            return "STAY"
