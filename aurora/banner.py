"""The pixel-font AURORA banner for the header.

Each pixel of a letter is two cells wide so that it looks square. A shadow sits one row down and
two cells right of the letters. The banner is split into zones by column. The caller gives each
zone its own colour, so the word shades from one end to the other.
"""

from collections import namedtuple

GLYPHS = {
    "A": [" ### ", "#   #", "#####", "#   #", "#   #"],
    "U": ["#   #", "#   #", "#   #", "#   #", " ### "],
    "R": ["#### ", "#   #", "#### ", "#  # ", "#   #"],
    "O": [" ### ", "#   #", "#   #", "#   #", " ### "],
}
WORD = "AURORA"
PIXEL_W = 2
GAP = 2
SHADOW = (1, 2)
ZONES = 6

# A run is text in one row, from column x, that shares a layer and a zone.
Run = namedtuple("Run", "y x text layer zone")
Banner = namedtuple("Banner", "height width runs")


def render(unicode=True):
    """Return the Banner. Letters use block characters when unicode is set and '#' and '.' otherwise."""
    face, shade = ("█", "░") if unicode else ("#", ".")
    rows = len(GLYPHS["A"])
    letter_w = len(GLYPHS["A"][0]) * PIXEL_W
    height = rows + SHADOW[0]
    width = len(WORD) * letter_w + (len(WORD) - 1) * GAP + SHADOW[1]
    grid = [[None] * width for _ in range(height)]
    for n, letter in enumerate(WORD):
        left = n * (letter_w + GAP)
        for y, line in enumerate(GLYPHS[letter]):
            for px, ch in enumerate(line):
                if ch != "#":
                    continue
                for dx in range(PIXEL_W):
                    x = left + px * PIXEL_W + dx
                    grid[y + SHADOW[0]][x + SHADOW[1]] = grid[y + SHADOW[0]][x + SHADOW[1]] or "shadow"
                    grid[y][x] = "face"
    runs = []
    for y, row in enumerate(grid):
        start, last = 0, None
        for x in range(width + 1):
            cell = row[x] if x < width else None
            key = None if cell is None else (cell, min(ZONES - 1, x * ZONES // width))
            if key != last:
                if last is not None:
                    layer, zone = last
                    runs.append(
                        Run(y, start, (face if layer == "face" else shade) * (x - start), layer, zone)
                    )
                start, last = x, key
    return Banner(height, width, runs)
