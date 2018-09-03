#!/usr/bin/python3

__doc__ = """
Generates N unique random positions for a given piece configuration
(e.g., KBNk).

Each position is white to move and is a forced win for white,
taking the 50-move rule into account.
The half-move clock is set at random within the above constraints.

The output is in EPD format, with these standard opcodes:
   id: Position identifer (based on --id_format)
   bm: Optimal moves (for shortest forced checkmate)
   am: Moves that allow black to draw or win
   dm: Number of full moves to mate with optimal play
       (this one does not take the 50-move rule into account)
and these private opcodes:
   R50: Present if the optimal moves would be different without the 50-move rule

Limitations:
* Needs both Syzygy and Gaviota EGTBs. Since Gaviota only goes up to 5 pieces,
  so does this script.
* Assumes that (hmvc + dtz <= 100) is a sufficient and necessary condition to
  guarantee a win. Since Syzygy's DTZ can be off by one, this may be inaccurate
  in positions where the winning sequence involves forcing Black to make a
  zeroing move.
"""

import argparse
import chess
import chess.gaviota
import chess.syzygy
import collections
import itertools
import os
import os.path
import random
import re
import sys

class Generator:
    def __init__(self, code: str, id_format: str, gaviota_tb, syzygy_tb):
        assert re.match(r'K[QRBNP]+k[qrbnp]*', code)
        self._code = code
        self._pieces = [chess.Piece.from_symbol(x) for x in code]
        self._id_format = id_format
        self._gaviota_tb = gaviota_tb
        self._syzygy_tb = syzygy_tb
        self._unique_boards = set()
        self.stats = collections.Counter()

    def generate_epd(self) -> str:
        for board in self._generate_boards():
            epd_info = self._annotate_board(board)
            yield board.epd(**epd_info)

    def _generate_boards(self) -> chess.Board:
        while True:
            squares = random.sample(chess.SQUARES, len(self._pieces))
            board = chess.Board.empty()
            board.set_piece_map(dict(zip(squares, self._pieces)))
            if not board.is_valid():
                self.stats['invalid'] += 1
                continue
            dtz = self._syzygy_tb.probe_dtz(board)
            if not 0 < dtz <= 100:
                # This covers checkmates/stalemates, too.
                self.stats['loss' if dtz < 0 else
                           'draw' if dtz == 0 else
                           'cursed_win'] += 1
                continue
            board.halfmove_clock = random.randint(0, 100 - dtz)
            board_key = board.fen()
            if board_key in self._unique_boards:
                self.stats['duplicate'] += 1
                continue
            self._unique_boards.add(board_key)
            yield board

    def _annotate_board(self, board: chess.Board) -> dict:
        epd_info = dict()

        epd_info['id'] = self._id_format.format(code=self._code,
                                                n=len(self._unique_boards))
        if board.halfmove_clock:
            epd_info['hmvc'] = board.halfmove_clock

        legal_moves = list(board.legal_moves)
        children_dtm = {move: self._child_dtm_if_lost(board, move)
                        for move in legal_moves}
        best_child_dtm = max(dtm for dtm in children_dtm.values()
                             if dtm is not None)
        optimal_moves = [move for move, dtm in children_dtm.items()
                         if dtm == best_child_dtm]
        epd_info['bm'] = optimal_moves
        bad_moves = [move for move, dtm in children_dtm.items()
                     if dtm is None]
        if bad_moves:
            epd_info['am'] = bad_moves

        parent_dtm = self._gaviota_tb.probe_dtm(board)
        assert 0 < parent_dtm <= 1 - best_child_dtm
        epd_info['dm'] = int((parent_dtm + 1) / 2)
        if parent_dtm < 1 - best_child_dtm:
            epd_info['R50'] = None

        return epd_info

    def _child_dtm_if_lost(self, board: chess.Board, move: chess.Move) -> int:
        """DTM after a move if the move is winning, otherwise None."""
        board.push(move)
        try:
            if board.is_game_over(claim_draw=True):
                return 0 if board.is_checkmate() else None
            dtz = self._syzygy_tb.probe_dtz(board)
            if not board.halfmove_clock - 100 <= dtz < 0:
                return None
            dtm = self._gaviota_tb.probe_dtm(board)
            assert dtm < 0
            return dtm
        finally:
            board.pop()

if __name__ == '__main__':
    argparser = argparse.ArgumentParser(
        description='Generate random chess positions.')
    argparser.add_argument('poscode')
    argparser.add_argument('n', type=int)
    argparser.add_argument('--output', type=argparse.FileType('w'),
                           default=sys.stdout)
    argparser.add_argument('--gaviota_path',
                           default=os.path.join(os.environ['HOME'],
                                                'chess/gtb'))
    argparser.add_argument('--syzygy_path',
                           default=os.path.join(os.environ['HOME'],
                                                'chess/syzygy'))
    argparser.add_argument('--id_format', default='{code}.{n:06d}')
    argparser.add_argument('-v', default=False, action='store_true')

    args = argparser.parse_args()

    with chess.gaviota.open_tablebases(args.gaviota_path) as gaviota_tb, \
         chess.syzygy.open_tablebases(args.syzygy_path) as syzygy_tb:
        generator = Generator(code=args.poscode, id_format=args.id_format,
                              gaviota_tb=gaviota_tb, syzygy_tb=syzygy_tb)
        epds = itertools.islice(generator.generate_epd(), args.n)
        args.output.writelines(epd + '\n' for epd in epds)
        args.output.flush()

        if (args.v):
            print(generator.stats, file=sys.stderr)
