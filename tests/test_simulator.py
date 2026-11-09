import unittest

from tools.simulate import Game, mirrored_map


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.game = Game([[1]*8 for _ in range(8)])

    def test_arrival_does_not_capture_and_stay_does(self):
        g = self.game
        g.step({1: "EAST"})
        self.assertEqual(g.board[0][1].owner, 0)
        g.step({1: "STAY"})
        self.assertEqual(g.board[0][1].owner, 1)
        self.assertEqual(g.scores[1], 3)

    def test_cannot_enter_cell_occupied_at_start_even_if_it_leaves(self):
        g = self.game
        g.positions[2] = (0, 1)
        g.step({1: "EAST", 2: "SOUTH"})
        self.assertEqual(g.positions[1], (0, 0))
        self.assertEqual(g.positions[2], (1, 1))
        self.assertEqual(g.progress[1], 1)

    def test_swaps_block_both_and_blocked_moves_count_as_stays(self):
        g = self.game
        g.positions[2] = (0, 1)
        g.step({1: "EAST", 2: "WEST"})
        self.assertEqual(g.positions[1:3], [(0, 0), (0, 1)])
        self.assertEqual(g.board[0][1].owner, 2)

    def test_owner_beats_priority_in_contest(self):
        g = self.game
        g.positions[2] = (0, 2)
        g.board[0][1].owner = 2
        g.step({1: "EAST", 2: "WEST"})
        self.assertEqual(g.positions[2], (0, 1))

    def test_token_wraparound_breaks_contest(self):
        g = self.game
        g.priority = 3
        g.positions[4] = (0, 2)
        g.step({1: "EAST", 4: "WEST"})
        self.assertEqual(g.positions[4], (0, 1))
        self.assertEqual(g.priority, 4)

    def test_three_stays_upgrade_and_capture_stay_is_not_upgrade_progress(self):
        g = self.game
        g.positions[1] = (1, 1)
        g.step({})
        self.assertEqual(g.progress[1], 0)
        for _ in range(2):
            g.step({})
            self.assertFalse(g.board[1][1].is_upgraded)
        g.step({})
        self.assertTrue(g.board[1][1].is_upgraded)

    def test_raid_bonus_uses_previous_level_and_capture_downgrades(self):
        g = self.game
        g.positions[1] = (1, 1)
        cell = g.board[1][1]
        cell.owner, cell.base_points, cell.is_upgraded = 2, 3, True
        for _ in range(2):
            g.step({})
            self.assertEqual(cell.owner, 2)
        before = g.scores[1]
        g.step({})
        self.assertEqual(cell.owner, 1)
        self.assertFalse(cell.is_upgraded)
        # Raid bonus 48 + captured cell 3 + own home 1.
        self.assertEqual(g.scores[1]-before, 52)

    def test_level_one_raid_bonus(self):
        g = self.game
        g.positions[1] = (1, 1)
        g.board[1][1].owner = 2
        g.step({})
        self.assertEqual(g.scores[1], 10)

    def test_enemy_home_cannot_be_captured(self):
        g = self.game
        g.positions[1], g.positions[2] = (0, 7), (1, 7)
        for _ in range(4):
            g.step({})
        self.assertEqual(g.board[0][7].owner, 2)
        self.assertEqual(g.progress[1], 0)

    def test_moving_resets_progress(self):
        g = self.game
        g.step({})
        g.step({})
        g.step({1: "EAST"})
        self.assertEqual(g.progress[1], 0)
        self.assertFalse(g.board[0][0].is_upgraded)

    def test_shield_catches_staying_attacker_and_blocks_two_future_turns(self):
        g = self.game
        g.positions[2] = (1, 1)
        g.board[1][1].owner = 1
        g.step({1: "SHIELD", 2: "STAY"})
        self.assertEqual(g.board[1][1].owner, 1)
        self.assertEqual(g.frozen[2], 2)
        self.assertEqual(g.frozen[1], 0)
        for remaining in (1, 0):
            self.assertEqual(g.legal_actions(2), ["STAY"])
            g.step({2: "EAST"})
            self.assertEqual(g.frozen[2], remaining)
            self.assertEqual(g.board[1][1].owner, 1)
            self.assertEqual(g.progress[2], 0)
        g.step({2: "STAY"})
        self.assertEqual(g.board[1][1].owner, 2)

    def test_shield_backfires_if_attacker_moves(self):
        g = self.game
        g.positions[2] = (1, 1)
        g.board[1][1].owner = 1
        g.step({1: "SHIELD", 2: "EAST"})
        self.assertEqual(g.frozen[1], 2)
        self.assertEqual(g.frozen[2], 0)

    def test_shield_arrival_does_not_catch(self):
        g = self.game
        g.positions[2] = (1, 2)
        g.board[1][1].owner = 1
        g.step({1: "SHIELD", 2: "WEST"})
        self.assertEqual(g.frozen[1], 2)
        self.assertEqual(g.frozen[2], 0)

    def test_shield_catches_blocked_move(self):
        g = self.game
        g.positions[2] = (0, 1)
        g.board[0][1].owner = 1
        g.step({1: "SHIELD", 2: "WEST"})
        self.assertEqual(g.frozen[2], 2)
        self.assertEqual(g.frozen[1], 0)

    def test_shield_cannot_refreeze_already_frozen_bot(self):
        g = self.game
        g.positions[2] = (1, 1)
        g.board[1][1].owner = 1
        g.frozen[2] = 1
        g.step({1: "SHIELD"})
        self.assertEqual(g.frozen[1], 2)
        self.assertEqual(g.frozen[2], 0)

    def test_shield_catches_multiple_bots_and_resets_raid_progress(self):
        g = self.game
        g.positions[2], g.positions[3] = (1, 1), (1, 2)
        for c in (1, 2):
            g.board[1][c].owner = 1
            g.board[1][c].is_upgraded = True
        g.progress[2], g.progress[3] = 1, 2
        g.step({1: "SHIELD"})
        self.assertEqual(g.frozen[1:4], [0, 2, 2])
        self.assertEqual(g.progress[2:4], [0, 0])
        self.assertEqual(g.board[1][2].owner, 1)

    def test_shield_catches_rival_staying_on_home(self):
        g = self.game
        g.positions[1], g.positions[2] = (1, 0), (0, 0)
        g.step({1: "SHIELD"})
        self.assertEqual(g.frozen[2], 2)
        self.assertEqual(g.frozen[1], 0)

    def test_two_shields_resolve_simultaneously_without_catching_each_other(self):
        g = self.game
        g.positions[1], g.positions[2] = (0, 7), (0, 0)
        g.step({1: "SHIELD", 2: "SHIELD"})
        self.assertEqual(g.frozen[1:3], [2, 2])
        self.assertEqual(g.cooldown[1:3], [4, 4])

    def test_cooldown_excludes_next_four_turns_and_shield_resets_progress(self):
        g = self.game
        g.progress[1] = 2
        g.step({1: "SHIELD"})
        self.assertEqual(g.progress[1], 0)
        for _ in range(4):
            self.assertNotIn("SHIELD", g.legal_actions(1))
            g.step({})
        self.assertIn("SHIELD", g.legal_actions(1))

    def test_snapshot_is_independent_and_only_documented_fields(self):
        g = self.game
        state = g.state(1)
        self.assertEqual(set(vars(state)), {"board", "bot_id", "is_priority_token", "legal_actions"})
        state.board[0][0].owner = 4
        self.assertEqual(g.board[0][0].owner, 1)
        g.positions[1] = (2, 3)
        g.frozen[1] = 1
        self.assertEqual(g.state(1).board[2][3].occupant, 1)
        self.assertTrue(g.state(1).board[2][3].is_frozen)

    def test_maps_are_mirrored(self):
        for seed in range(10):
            values = mirrored_map(seed)
            for r in range(8):
                for c in range(8):
                    self.assertEqual(values[r][c], values[7-r][7-c])
                    self.assertEqual(values[r][c], values[7-r][c])
                    self.assertIn(values[r][c], (1, 2, 3))


if __name__ == "__main__":
    unittest.main()
