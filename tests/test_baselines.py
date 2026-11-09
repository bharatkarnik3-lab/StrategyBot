"""Behavioral checks for the stronger public-information benchmark opponent."""
import copy
import unittest

from tools.simulate import Baseline, Game, play


class FortressTests(unittest.TestCase):
    def setUp(self):
        self.game = Game([[1] * 8 for _ in range(8)])
        self.bot = Baseline("fortress", seed=42)
        self.game.positions[1] = (2, 2)
        here = self.game.board[2][2]
        here.owner, here.base_points = 1, 3

    def action(self):
        state = self.game.state(1)
        before = copy.deepcopy(state)
        action = self.bot.act(state)
        self.assertEqual(state, before)
        self.assertIn(action, state.legal_actions)
        return action

    def test_finishes_valuable_upgrade_before_expanding(self):
        for _ in range(3):
            self.assertEqual(self.action(), "STAY")
            self.game.step({1: "STAY"})
        self.assertTrue(self.game.board[2][2].is_upgraded)
        self.assertNotEqual(self.action(), "STAY")

    def test_does_not_start_unfinishable_endgame_upgrade(self):
        self.bot.turn = 78  # Two actions remain.
        self.game.board[2][3].base_points = 3
        self.assertEqual(self.action(), "EAST")
        self.game.step({1: "EAST"})
        self.assertEqual(self.action(), "STAY")
        self.game.step({1: "STAY"})
        self.assertEqual(self.game.board[2][3].owner, 1)
        self.assertFalse(self.game.board[2][2].is_upgraded)

    def test_finishes_two_stay_upgrade_on_last_turn(self):
        for _ in range(2):
            self.assertEqual(self.action(), "STAY")
            self.game.step({1: "STAY"})
        self.bot.turn = 79
        self.assertEqual(self.action(), "STAY")
        self.game.step({1: "STAY"})
        self.assertTrue(self.game.board[2][2].is_upgraded)

    def test_shields_eligible_intruder(self):
        self.game.positions[2] = (3, 3)
        self.game.board[3][3].owner = 1
        self.assertEqual(self.action(), "SHIELD")
        self.game.step({1: "SHIELD", 2: "STAY"})
        self.assertEqual(self.game.frozen[2], 2)
        self.assertEqual(self.game.frozen[1], 0)

    def test_does_not_shield_already_frozen_intruder(self):
        self.game.positions[2] = (3, 3)
        self.game.board[3][3].owner = 1
        self.game.frozen[2] = 2
        self.assertEqual(self.action(), "STAY")

    def test_complete_game_respects_public_interface(self):
        controllers = [Baseline("fortress", seed=seat) for seat in range(4)]
        game, _ = play(controllers, seed=91, check_inputs=True)
        self.assertEqual(game.turn, 80)
        self.assertTrue(all(score > 0 for score in game.scores[1:]))


if __name__ == "__main__":
    unittest.main()
