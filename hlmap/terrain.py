"""Open terrain for outdoor rooms: hills and lawns as a heightfield of brush columns.

GoldSrc has no displacements (that's Source). Terrain here is the cave's proven
construction opened to the sky: a grid whose cells split into two triangles, each a
column brush from the room floor up to a sloped top through its three corner heights.
Neighbouring columns share exact vertical faces on integer grid points, so the ground
is watertight by construction.

    hills = lvl.terrain("grounds", outdoor, height=lambda x, y: ..., cell=128,
                        flat=[(x0, y0, x1, y1), ...])      # roads, lots: bare floor

Heights are above the room floor, rounded to integers. Grid points on or inside a
`flat` rectangle get height 0; a column whose three corners are all 0 is left out,
so the room's own floor shows there (texture it as asphalt). Put flat rectangles on
the grid (multiples of `cell` from the room's corner) for straight edges.
"""
from __future__ import annotations

import math

from .geometry import Brush, face_from_points


class Terrain:
    def __init__(self, name, room, height, cell=128, flat=(), top="-0OUT_GRSS1", steep="-0OUT_GRND2B",
                 side="OUT_WLK", steep_below=0.8, max_height=None):
        self.name, self.room, self.cell = name, room, cell
        self.top, self.steep, self.side, self.steep_below = top, steep, side, steep_below
        (x0, y0, z0), (x1, y1, z1) = room.mins, room.maxs
        self.x0, self.y0, self.z0 = x0, y0, z0
        self.nx = math.ceil((x1 - x0) / cell)
        self.ny = math.ceil((y1 - y0) / cell)
        self.xs = [min(x0 + i * cell, x1) for i in range(self.nx + 1)]
        self.ys = [min(y0 + j * cell, y1) for j in range(self.ny + 1)]
        top_limit = (max_height if max_height is not None else (z1 - z0) - 64)
        self.flat = [tuple(r) for r in flat]
        self.h = {}
        for i, x in enumerate(self.xs):
            for j, y in enumerate(self.ys):
                if any(a <= x <= c and b <= y <= d for a, b, c, d in self.flat):
                    self.h[i, j] = 0
                else:
                    self.h[i, j] = max(0, min(top_limit, int(round(height(x, y)))))

    # ------------------------------------------------------------ triangles
    def _tris(self, i, j):
        """The cell's two triangles as corner index lists, counter-clockwise from above."""
        a, b, c, d = (i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)
        if (i + j) % 2 == 0:
            return [(a, b, c), (a, c, d)]
        return [(a, b, d), (b, c, d)]

    def _pt(self, k):
        return (self.xs[k[0]], self.ys[k[1]])

    def surface(self, x, y):
        """Ground height (absolute z) at (x, y), or None outside the terrain."""
        if not (self.xs[0] <= x <= self.xs[-1] and self.ys[0] <= y <= self.ys[-1]):
            return None
        i = min(self.nx - 1, max(0, int((x - self.x0) // self.cell)))
        j = min(self.ny - 1, max(0, int((y - self.y0) // self.cell)))
        for tri in self._tris(i, j):
            p = [self._pt(k) for k in tri]
            w = _bary(p, (x, y))
            if w and min(w) >= -1e-9:
                return self.z0 + sum(wk * self.h[k] for wk, k in zip(w, tri))
        return self.z0 + self.h[i, j]

    def in_ground(self, p, tol=0.0):
        """Is p inside the ground (by more than tol)?"""
        s = self.surface(p[0], p[1])
        return s is not None and p[2] < s - tol and p[2] >= self.z0 - tol

    # ------------------------------------------------------------ brushes
    def brushes(self):
        out = []
        z0 = self.z0
        for i in range(self.nx):
            for j in range(self.ny):
                for tri in self._tris(i, j):
                    hs = [self.h[k] for k in tri]
                    if max(hs) == 0:
                        continue
                    pts = [self._pt(k) for k in tri]
                    top = [(x, y, z0 + h) for (x, y), h in zip(pts, hs)]
                    # slope of the top: steep faces get the steep texture
                    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = top
                    n = ((by - ay) * (cz - az) - (bz - az) * (cy - ay), (bz - az) * (cx - ax) - (bx - ax) * (cz - az),
                         (bx - ax) * (cy - ay) - (by - ay) * (cx - ax))
                    nz = abs(n[2]) / math.sqrt(sum(c * c for c in n))
                    faces = [face_from_points(top[0], top[1], top[2], self.top if nz >= self.steep_below else self.steep),
                             face_from_points((pts[2][0], pts[2][1], z0), (pts[1][0], pts[1][1], z0),
                                              (pts[0][0], pts[0][1], z0), self.side)]
                    for (a, ha), (b, hb) in zip(zip(pts, hs), list(zip(pts, hs))[1:] + [(pts[0], hs[0])]):
                        if ha == 0 and hb == 0:
                            continue          # zero-height side: the sloped top closes it
                        faces.append(face_from_points((a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z0 + 64), self.side))
                    out.append(Brush(faces, f"{self.name} terrain"))
        return out

    def emit(self, m):
        m.add_world(*self.brushes())

    def check(self, level):
        problems = []
        (x0, y0, _), (x1, y1, z1) = self.room.mins, self.room.maxs
        top = max(self.h.values()) + self.z0
        if top > z1 - 32:
            problems.append(f"terrain {self.name}: heights reach {top}, too close to the sky at {z1}")
        return problems


def _bary(tri, p):
    (x1, y1), (x2, y2), (x3, y3) = tri
    det = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if det == 0:
        return None
    a = ((y2 - y3) * (p[0] - x3) + (x3 - x2) * (p[1] - y3)) / det
    b = ((y3 - y1) * (p[0] - x3) + (x1 - x3) * (p[1] - y3)) / det
    return (a, b, 1 - a - b)
