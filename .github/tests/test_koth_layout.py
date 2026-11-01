"""The approved two-column design, including live changes and crowded screens."""
import copy
import os
import unittest
from unittest.mock import patch

from ctfd_monitor import app as m


class KothLayoutTests(unittest.TestCase):
    def setUp(self):
        enabled = patch.object(m, 'KOTH_ENABLED', True)
        enabled.start(); self.addCleanup(enabled.stop)
        sources = patch.object(m, 'KOTH_SOURCES', {str(i): {'max_points': 1500} for i in (101,102,103,*range(201,221))})
        sources.start(); self.addCleanup(sources.stop)

    def view(self, unsolved=9, solved=3):
        view = m.SharedState().view()
        challenges = {str(i): dict(id=i, name=f'Problem {i}', category=f'Category {i // 3}',
                                   value=100, solved=i > unsolved, type='standard')
                      for i in range(1, unsolved + solved + 1)}
        arenas = {str(i): dict(id=i, name=name, points=points, rank=rank, teams=12,
                              status='LIVE', team_points={'1': points + 20, '7': points})
                  for i, name, points, rank in ((101, 'Arena Alpha', 1250, 2),
                                               (102, 'Arena Beta', 1500, 1),
                                               (103, 'Arena Gamma', 730, 4))}
        view.update(status='LIVE', team_name='Ours', account_id=7, rank='#2', score=3480 + solved * 100,
                    challenges=challenges, koth=arenas, codex_usage={'status': 'LIVE', 'remaining_percent': 68},
                    scoreboard=[dict(account_id=i, pos=rank, name='Ours' if i == 7 else f'Team {i}',
                                     score=5000 - rank * 100, solved_challenge_ids=list(range(1, unsolved + solved + 1)) if i == 7 else [])
                                for rank, i in enumerate((1, 7, 3, 4, 5), 1)])
        return view

    def plain(self, rows):
        return [m.ANSI_RE.sub('', line) for line in rows]

    def test_fewer_challenges_choose_side_and_ties_choose_solved(self):
        for width in (109, 110, 120, 140, 220):
            left_width = (width - 2) // 2
            for unsolved, solved in ((9, 3), (3, 9), (0, 0), (0, 12), (12, 0), (6, 6)):
                view = self.view(unsolved, solved)
                # KOTH challenges must not affect either the counts or side.
                view['challenges'].update({str(i): dict(id=i, name=f'Koth {i}', type='koth', category='koth', solved=False)
                                           for i in range(201, 221)})
                rows = self.plain(m.render_challenges(view, left_width, width - 2 - left_width))
                headers = [(i, line.index('KOTH ·')) for i, line in enumerate(rows) if 'KOTH ·' in line]
                self.assertEqual(len(headers), 1)
                row, column = headers[0]
                self.assertEqual(column < left_width, unsolved < solved, (width, unsolved, solved))
                self.assertGreater(row, 1)
                self.assertIn('└', rows[row - 1][:left_width] if unsolved < solved else rows[row - 1][left_width + 2:])
                self.assertIn(f'UNSOLVED  {unsolved}', rows[0])
                self.assertIn(f'SOLVED  {solved}', rows[0])
                self.assertTrue(all(m.display_width(line) == width for line in rows))

    def test_live_solves_move_card_without_duplication_or_mutating_data(self):
        view = self.view(12, 0)
        for solved in range(13):
            for challenge in view['challenges'].values():
                challenge['solved'] = challenge['id'] <= solved
            before = copy.deepcopy(view)
            rows = self.plain(m.render_challenges(view, 59, 59))
            line = next(row for row in rows if 'KOTH ·' in row)
            self.assertEqual(line.index('KOTH ·') < 59, 12 - solved < solved)
            self.assertEqual(sum('KOTH ·' in row for row in rows), 1)
            self.assertEqual(view, before)

    def test_side_uses_problem_count_even_when_categories_make_it_taller(self):
        view = self.view(2, 3)
        for c in view['challenges'].values():
            c['category'] = f'Category {c["id"]}' if not c['solved'] else 'Common'
        rows = self.plain(m.render_challenges(view, 59, 59))
        self.assertLess(next(row for row in rows if 'KOTH ·' in row).index('KOTH ·'), 59)

    def test_runtime_koth_appearance_disappearance_and_prestart(self):
        view = self.view(3, 9)
        arenas = view['koth']
        for active in (False, True, False, True):
            view['koth'] = arenas if active else {}
            text = '\n'.join(self.plain(m.render_challenges(view, 59, 59)))
            self.assertEqual('KOTH ·' in text, active)
        view['status'] = 'PRE-START'
        rows = self.plain(m.render_challenges(view, 59, 59))
        self.assertIn('UNSOLVED  0', rows[0])
        self.assertIn('SOLVED  0', rows[0])
        self.assertGreater(next(row for row in rows if 'KOTH ·' in row).index('KOTH ·'), 59)

    def test_approved_card_has_two_lines_per_arena_and_full_width_bars(self):
        rows = m.render_koth(self.view(), 59)
        plain = self.plain(rows)
        self.assertEqual(len(rows), 10)
        self.assertIn('KOTH · 3 ARENAS · 3480 / 4500 pt', plain[0])
        for name, rank, points, name_row in (('Arena Alpha', 2, '1250', 1), ('Arena Beta', 1, '1500', 4), ('Arena Gamma', 4, '730', 7)):
            self.assertIn(name, plain[name_row])
            self.assertIn(f'Rank #{rank}/12', plain[name_row])
            self.assertIn(m.BOLD + m.WHITE, rows[name_row])
            self.assertIn(m.GRAY, rows[name_row])
            self.assertIn(f'{points} / 1500 pt', plain[name_row + 1])
            self.assertEqual(sum(plain[name_row + 1].count(c) for c in '█░'), 39)
            self.assertIn(m.GREEN, rows[name_row + 1])
        self.assertEqual(plain[3].strip(), '│' + ' ' * 57 + '│')

    def test_fitting_preserves_borders_and_reports_omitted_rows(self):
        view = self.view(40, 40)
        for budget in range(30):
            rows = self.plain(m.render_challenges(view, 59, 59, max_rows=budget))
            self.assertLessEqual(len(rows), budget)
            self.assertTrue(all(m.display_width(line) == 120 for line in rows))
            if budget >= 6:
                self.assertEqual(sum('KOTH ·' in row for row in rows), 1)
                self.assertIn('more rows', '\n'.join(rows))
                self.assertIn('└', rows[-1][61:])
            if budget >= 13:
                for arena in ('Arena Alpha', 'Arena Beta', 'Arena Gamma'):
                    self.assertIn(arena, '\n'.join(rows))

    def test_real_screen_keeps_graphs_codex_colors_and_both_comparisons(self):
        resources = dict(now=240, cpu=17, memory=31.6, samples=[(120 + i, i % 47, 31.6) for i in range(120)])
        for cols, height in ((109, 54), (110, 54), (120, 61), (140, 61), (220, 80)):
            for unsolved, solved in ((9, 3), (3, 9), (80, 0), (40, 40), (0, 80)):
                with self.subTest(cols=cols, height=height, unsolved=unsolved), patch.object(m.shutil, 'get_terminal_size', return_value=os.terminal_size((cols, height))):
                    text = m.render_screen(self.view(unsolved, solved), resources)
                plain = m.ANSI_RE.sub('', text)
                for label in ('CPU', 'MEMORY', '100% ┤', '0% └', 'CODEX WEEKLY', 'TEAM COMPARISON', 'JEOPARDY CHALLENGE', 'Arena Alpha', 'Arena Beta', 'Arena Gamma'):
                    self.assertIn(label, plain)
                self.assertIn(m.OWN_TEAM_BG, text)
                self.assertIn(m.RED_BG, text)
                self.assertTrue(all(line.startswith(m.SCREEN_STYLE) for line in text.splitlines()))
                self.assertLessEqual(len(text.splitlines()), height)
                self.assertTrue(all(m.display_width(line) == cols for line in text.splitlines()))
                self.assertEqual(plain.count('KOTH ·'), 1)


if __name__ == '__main__':
    unittest.main()
