"""Contract and tactical regression checks against public input snapshots."""
import ast
import copy
from pathlib import Path
import unittest

from tools.simulate import Game, load_bot

BOT_PATH = Path(__file__).resolve().parents[1] / "bot.py"


class BotTests(unittest.TestCase):
    def setUp(self):
        self.bot = load_bot(BOT_PATH, "tested_candidate")
        self.game = Game([[1]*8 for _ in range(8)])

    def act(self, legal=None):
        state = self.game.state(1)
        if legal is not None:
            state.legal_actions = legal
        before = copy.deepcopy(state)
        action = self.bot.act(state)
        self.assertEqual(state, before, "act must not mutate the input")
        self.assertIn(action, state.legal_actions)
        return action

    def progress(self):
        return self.bot._MEMORY[1]["progress"].get(1, 0)

    def test_standard_library_only_and_signature(self):
        tree = ast.parse(BOT_PATH.read_text())
        import sys
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    self.assertIn(name.name.split(".")[0], sys.stdlib_module_names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)
                self.assertIn(node.module.split(".")[0], sys.stdlib_module_names)
        entry = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "act")
        self.assertEqual([a.arg for a in entry.args.args], ["state"])

    def test_legal_action_and_immutability_for_every_seat(self):
        for seat in range(1, 5):
            module = load_bot(BOT_PATH, f"seat_{seat}")
            state = self.game.state(seat)
            before = copy.deepcopy(state)
            self.assertIn(module.act(state), state.legal_actions)
            self.assertEqual(state, before)

    def test_failed_requested_move_is_observed_as_stay_progress(self):
        g = self.game
        g.positions[2] = (0, 2)
        g.priority = 2
        self.assertEqual(self.act(["EAST"]), "EAST")
        g.step({1: "EAST", 2: "WEST"})
        self.assertEqual(g.positions[1], (0, 0))
        self.act(["STAY"])
        self.assertEqual(self.progress(), 1)

    def test_capture_is_not_counted_as_an_upgrade_stay(self):
        g = self.game
        g.positions[1] = (1, 1)
        self.act(["STAY"])
        g.step({1: "STAY"})
        self.act(["STAY"])
        self.assertEqual(self.progress(), 0)
        g.step({1: "STAY"})
        self.act(["STAY"])
        self.assertEqual(self.progress(), 1)

    def test_freeze_clears_progress_and_thaw_resumes_from_zero(self):
        g = self.game
        g.positions[1] = (1, 1)
        g.board[1][1].owner = 2
        g.board[1][1].is_upgraded = True
        self.act(["STAY"])
        g.step({1: "STAY"})
        self.act(["STAY"])
        self.assertEqual(self.progress(), 1)
        g.step({1: "STAY"})
        self.act(["STAY"])
        self.assertEqual(self.progress(), 2)
        g.step({1: "STAY", 2: "SHIELD"})
        self.assertEqual(self.act(), "STAY")
        self.assertEqual(self.progress(), 0)
        g.step({1: "STAY"})
        self.assertEqual(self.act(), "STAY")
        self.assertEqual(self.progress(), 0)
        g.step({1: "STAY"})
        self.act(["STAY"])
        self.assertEqual(self.progress(), 0)
        g.step({1: "STAY"})
        self.act(["STAY"])
        self.assertEqual(self.progress(), 1)

    def test_new_module_has_no_previous_game_memory(self):
        self.act()
        other = load_bot(BOT_PATH, "fresh_game")
        self.assertEqual(other._MEMORY, {})
        other.act(self.game.state(1))
        self.assertIsNot(other._MEMORY, self.bot._MEMORY)
        self.assertEqual(other._MEMORY[1]["turn"], 0)

    def test_every_single_legal_action_is_respected(self):
        for action in ("NORTH", "EAST", "SOUTH", "WEST", "STAY", "SHIELD"):
            self.assertEqual(self.act([action]), action)

    def test_all_occupied_neighbors_are_avoided(self):
        g = self.game
        g.positions[2], g.positions[3] = (0, 1), (1, 0)
        g.board[0][0].is_upgraded = True
        self.assertEqual(self.act(), "STAY")

    def test_shield_is_not_used_without_eligible_victim(self):
        self.assertNotEqual(self.act(), "SHIELD")
        g = self.game
        g.positions[2] = (1, 1)
        g.board[1][1].owner = 1
        g.frozen[2] = 1
        self.assertNotEqual(self.act(), "SHIELD")

    def test_final_turn_takes_available_raid_instead_of_moving(self):
        g = self.game
        g.positions[1] = (3, 3)
        g.board[3][3].owner = 2
        g.board[3][3].base_points = 3
        self.act(["STAY"])
        # The interface supplies no turn counter; memory counts actual calls.
        self.bot._MEMORY[1]["turn"] = 78
        self.assertEqual(self.act(), "STAY")

    def test_final_turn_does_not_shield_unfinishable_enemy_raid(self):
        g = self.game
        g.positions[1] = (3, 3)
        g.board[3][3].base_points = 3
        g.positions[2] = (4, 4)
        cell = g.board[4][4]
        cell.owner, cell.base_points, cell.is_upgraded = 1, 3, True
        self.act(["STAY"])
        # One observed rival stay leaves two more required, but only one turn
        # remains. Taking our neutral cell produces three certain points.
        self.bot._MEMORY[1]["turn"] = 78
        self.assertEqual(self.act(), "STAY")

    def test_own_shield_backfire_on_enemy_land_does_not_invent_enemy_cooldown(self):
        g = self.game
        g.positions[1] = (1, 1)
        g.board[1][1].owner = 2
        self.assertEqual(self.act(["SHIELD"]), "SHIELD")
        g.step({1: "SHIELD"})
        self.assertEqual(self.act(), "STAY")
        shields = self.bot._MEMORY[1]["shields"]
        self.assertEqual(shields[1], 0)
        self.assertNotIn(2, shields)

    def test_ambiguous_rival_freeze_does_not_invent_landowner_cooldown(self):
        g = self.game
        g.positions[2] = (1, 1)
        g.board[1][1].owner = 3
        self.act(["STAY"])
        g.step({2: "SHIELD"})
        self.act(["STAY"])
        # The public snapshot cannot distinguish seat 2 backfiring from
        # seat 3 successfully shielding. Neither cooldown is certain.
        shields = self.bot._MEMORY[1]["shields"]
        self.assertNotIn(2, shields)
        self.assertNotIn(3, shields)

    def test_flat_board_compatibility_with_skeleton_description(self):
        state = self.game.state(1)
        state.board = [cell for row in state.board for cell in row]
        before = copy.deepcopy(state)
        self.assertIn(self.bot.act(state), state.legal_actions)
        self.assertEqual(state, before)


if __name__ == "__main__":
    unittest.main()
