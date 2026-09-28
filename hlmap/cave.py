"""Organic caves as a 2.5-D heightfield of simple convex columns.

A cave leaves a room through a hole in one of its walls and follows a floor path.
Around the path an axis-aligned grid (`cell` units) is laid out. Every grid vertex
gets a floor and a ceiling height: a flat walkable floor near the path, the floor
rising and the ceiling falling towards the edge, where they meet ("closed"). Each
grid cell is split into two triangles and every triangle becomes

    a floor prism   - sloped top through the 3 floor heights, flat bottom, and
    a ceiling prism - sloped bottom through the 3 ceiling heights, flat top,

or one full column where the triangle is closed. Cells away from the cave are full
solid columns. That is the classic GoldSrc terrain construction, and it is exact:

  * every vertex is an integer grid point;
  * every side face is a vertical plane through a shared grid edge, so neighbours
    share faces exactly: no gaps, no overlaps, no slivers;
  * the band of cells extends at least two cells past any open vertex and ends in
    solid columns, so the cave is sealed by construction.

Thick, vertical-sided convex brushes are also what the compilers' collision hulls
handle reliably. (The earlier lofted-ring tunnel made of thin slanted rock plates
compiled, but playtesting found walk-through walls and see-through faces.)

Limitation: 2.5-D - one span of air per (x, y), so no overhangs or stacked passages.
"""
from __future__ import annotations

import math
import random

from .geometry import Brush, face_from_points, make_face
from .level import Material

ROCK = Material(floor="-0OUT_DIRT2", wall="-0OUT_RK3", ceiling="-0OUT_RK3")


def _smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _catmull_rom(points, samples=24):
    pts = [points[0]] + list(points) + [points[-1]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for k in range(samples):
            t = k / samples
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[c]) + (-p0[c] + p2[c]) * t + (2 * p0[c] - 5 * p1[c] + 4 * p2[c] - p3[c]) * t2
                                    + (-p0[c] + 3 * p1[c] - 3 * p2[c] + p3[c]) * t3) for c in range(3)))
    out.append(tuple(points[-1]))
    return out


class _Noise2:
    """Smooth value noise on a square lattice (spacing in world units), in [-1, 1]."""

    def __init__(self, seed, spacing):
        self.seed, self.spacing, self.cache = seed, spacing, {}

    def _v(self, i, j):
        v = self.cache.get((i, j))
        if v is None:
            v = self.cache[(i, j)] = random.Random(f"{self.seed}:{i}:{j}").uniform(-1, 1)
        return v

    def __call__(self, x, y):
        fx, fy = x / self.spacing, y / self.spacing
        i, j = math.floor(fx), math.floor(fy)
        tx, ty = _smoothstep(fx - i), _smoothstep(fy - j)
        a = self._v(i, j) + (self._v(i + 1, j) - self._v(i, j)) * tx
        b = self._v(i, j + 1) + (self._v(i + 1, j + 1) - self._v(i, j + 1)) * tx
        return a + (b - a) * ty


class _Noise1:
    def __init__(self, seed, spacing, count=512):
        rnd = random.Random(seed)
        self.vals = [rnd.uniform(-1, 1) for _ in range(count)]
        self.spacing = spacing

    def __call__(self, s):
        f = max(0.0, s) / self.spacing
        i = int(f)
        t = _smoothstep(f - i)
        a, b = self.vals[i % len(self.vals)], self.vals[(i + 1) % len(self.vals)]
        return a + (b - a) * t


class _Path:
    """One passage of a cave: a smoothed floor polyline plus its size profile."""

    def __init__(self, points, width, height, scale, flare, mouth_size, materials, seed):
        dense = _catmull_rom([tuple(p) for p in points])
        self.poly, s = [dense[0]], [0.0]
        for p in dense[1:]:
            step = math.hypot(p[0] - self.poly[-1][0], p[1] - self.poly[-1][1])
            if step > 0.5:
                self.poly.append(p)
                s.append(s[-1] + step)
        self.poly_s = s
        self.length = s[-1]
        self.width, self.height = width, height
        self.scale = scale or (lambda f: 1.0)
        self.flare = flare
        self.mouth_size = mouth_size          # (w, h) for the main path, None for branches
        self.materials = sorted(materials, key=lambda m: m[0])
        self.n_width = (_Noise1(f"{seed}r", 96), _Noise1(f"{seed}l", 96))

    def nearest(self, x, y):
        """(s, distance, side(+1 right / -1 left), floor z, tangent) of the closest point."""
        best = None
        P = self.poly
        for k in range(len(P) - 1):
            a, b = P[k], P[k + 1]
            ex, ey = b[0] - a[0], b[1] - a[1]
            L2 = ex * ex + ey * ey
            t = max(0.0, min(1.0, ((x - a[0]) * ex + (y - a[1]) * ey) / L2)) if L2 else 0.0
            px, py = a[0] + ex * t, a[1] + ey * t
            dd = (x - px) ** 2 + (y - py) ** 2
            if best is None or dd < best[0]:
                best = (dd, k, t, px, py, ex, ey)
        dd, k, t, px, py, ex, ey = best
        s = self.poly_s[k] + (self.poly_s[k + 1] - self.poly_s[k]) * t
        z = P[k][2] + (P[k + 1][2] - P[k][2]) * t
        L = math.hypot(ex, ey) or 1.0
        side = 1 if (ex * (y - py) - ey * (x - px)) < 0 else -1
        return s, math.sqrt(dd), side, z, (ex / L, ey / L)

    def dims(self, s, side=0):
        """(half width, height, flare factor) at arc length s."""
        f = _smoothstep(s / self.flare) if self.flare else 1.0
        k = self.scale(s / self.length)
        if self.mouth_size:
            mw, mh = self.mouth_size
            hw = (mw / 2 + (self.width / 2 - mw / 2) * f) * k
            h = (mh + (self.height - mh) * f) * k
        else:
            hw, h = self.width / 2 * k, self.height * k
        if side:
            hw *= 1 + 0.25 * f * self.n_width[0 if side > 0 else 1](s)
        return hw, h, f

    def at_s(self, s):
        P, S = self.poly, self.poly_s
        s = max(0.0, min(self.length, s))
        for k in range(len(P) - 1):
            if S[k + 1] >= s:
                t = (s - S[k]) / (S[k + 1] - S[k]) if S[k + 1] > S[k] else 0
                a, b = P[k], P[k + 1]
                L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
                return ((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t),
                        ((b[0] - a[0]) / L, (b[1] - a[1]) / L))
        a, b = P[-2], P[-1]
        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        return (b[0], b[1], b[2]), ((b[0] - a[0]) / L, (b[1] - a[1]) / L)


class Cave:
    def __init__(self, name, mouth, direction, mouth_size, path, *, cell=32, width=176, height=144,
                 roughness=16, floor_noise=3, flare=128, seed=0, materials=((0.0, ROCK),), blend=0.0,
                 scale=None, avoid=(), branches=()):
        """
        mouth:      floor centre of the doorway on the OUTER face of the room wall.
        direction:  axis unit vector (dx, dy) pointing out of the room.
        mouth_size: (width, height) of the doorway; width must be a multiple of `cell`.
        path:       floor-centre control points after the mouth (z = floor height).
        width/height: full cave size (the floor is flat over the middle half).
        materials:  [(start_fraction, Material)]; `blend` makes boundaries ragged.
        scale:      optional f(fraction) -> size multiplier (chambers).
        avoid:      air boxes of other rooms the cave must keep clear of.
        branches:   side passages: [{"at": fraction of the main path where it leaves,
                    "path": [floor points...], optional "width", "height", "scale",
                    "materials"}]. Branch k is addressed as branch=k+1 in floor_point(),
                    camera() and frame().
        """
        self.name = name
        self.cell = cell
        self.width, self.height = width, height
        self.roughness, self.floor_noise = roughness, floor_noise
        self.flare = flare
        self.materials = sorted(materials, key=lambda m: m[0])
        self.blend = blend
        self.scale = scale or (lambda s: 1.0)
        self.mouth, self.dir, self.mouth_size = tuple(mouth), tuple(direction), tuple(mouth_size)
        mw, mh = mouth_size
        if mw % cell:
            raise ValueError(f"cave {name}: mouth width {mw} must be a multiple of cell {cell}")
        self._n_floor = _Noise2(f"{seed}f", cell * 3)
        self._n_ceil = _Noise2(f"{seed}c", cell * 2.5)
        self._n_mat = _Noise2(f"{seed}m", cell * 2)

        # --- the paths: main (from the mouth) + branches ---------------------------
        d = self.dir
        lead = (mouth[0] + d[0] * 64, mouth[1] + d[1] * 64, mouth[2])
        main = _Path([tuple(mouth), lead] + [tuple(p) for p in path], width, height, scale, flare,
                     tuple(mouth_size), self.materials, seed)
        self.paths = [main]
        for k, br in enumerate(branches):
            start, _ = main.at_s(br["at"] * main.length)
            self.paths.append(_Path([start] + [tuple(p) for p in br["path"]], br.get("width", width),
                                    br.get("height", height), br.get("scale"), 0, None,
                                    br.get("materials", self.materials), f"{seed}b{k}"))
        self.length = main.length

        # --- grid: axis = outward axis, i >= 0 outward from the wall face ----------
        self.axis = 0 if d[0] else 1
        self.other = 1 - self.axis
        self.sign = d[self.axis]
        self.face = mouth[self.axis]
        self.o0 = mouth[self.other] - mw / 2
        self.mouth_cells = mw // cell
        self._build(avoid)

    # ------------------------------------------------------------ coordinates
    def _xy(self, i, j):
        a = self.face + self.sign * i * self.cell
        o = self.o0 + j * self.cell
        return (a, o) if self.axis == 0 else (o, a)

    def _ij(self, x, y):
        a, o = (x, y) if self.axis == 0 else (y, x)
        return (a - self.face) * self.sign / self.cell, (o - self.o0) / self.cell

    # ------------------------------------------------------------ path queries
    def _heights(self, x, y):
        """(floor, ceiling) at a grid vertex; equal when closed. The air of all paths is
        merged (union of their spans)."""
        opened, closed = [], []
        for path in self.paths:
            s, dist, side, zf, _ = path.nearest(x, y)
            hw, h, f = path.dims(s, side)
            t = dist / hw
            edge = zf + 0.55 * h + self.roughness * 0.5 * self._n_ceil(x, y) * f
            if t >= 1:
                closed.append((t, edge))
                continue
            rise = _smoothstep((t - 0.5) / 0.5)
            floor = zf + self.floor_noise * self._n_floor(x, y) * f * (1 - rise) + (edge - zf) * rise
            ceil = zf + h * (0.55 + 0.45 * math.sqrt(1 - t * t)) + self.roughness * 0.6 * self._n_ceil(x, y) * f
            if ceil - floor < 4:
                closed.append((t, (ceil + floor) / 2))
            else:
                opened.append((floor, ceil))
        if opened:
            return min(f for f, _ in opened), max(c for _, c in opened)
        edge = min(closed)[1]
        return edge, edge

    def _nearest_path(self, x, y):
        """(path, s) of the path whose air is relatively closest to (x, y)."""
        best = None
        for path in self.paths:
            s, dist, side, _, _ = path.nearest(x, y)
            t = dist / path.dims(s, side)[0]
            if best is None or t < best[0]:
                best = (t, path, s)
        return best[1], best[2]

    # ------------------------------------------------------------ grid build
    def _build(self, avoid):
        c = self.cell
        mw, mh = self.mouth_size
        z0 = self.mouth[2]
        cells = set()
        for path in self.paths:
            R = path.width / 2 * max(path.scale(k / 20) for k in range(21)) * 1.3 + 2.5 * c
            ii, jj = [], []
            for p in path.poly:
                i, j = self._ij(p[0], p[1])
                ii.append(i)
                jj.append(j)
            r = R / c
            i_lo, i_hi = max(0, math.floor(min(ii) - r) - 1), math.ceil(max(ii) + r) + 1
            j_lo, j_hi = math.floor(min(jj) - r) - 1, math.ceil(max(jj) + r) + 1
            for i in range(i_lo, i_hi):
                for j in range(j_lo, j_hi):
                    cx, cy = self._xy(i + 0.5, j + 0.5)
                    if (i, j) not in cells and path.nearest(cx, cy)[1] <= R:
                        cells.add((i, j))
        # cells overlapping other rooms' air are left out (those rooms' shells take over)
        blocked = set()
        for (i, j) in cells:
            (x0, y0), (x1, y1) = self._xy(i, j), self._xy(i + 1, j + 1)
            lo, hi = (min(x0, x1), min(y0, y1)), (max(x0, x1), max(y0, y1))
            for box in avoid:
                if lo[0] < box.maxs[0] and box.mins[0] < hi[0] and lo[1] < box.maxs[1] and box.mins[1] < hi[1]:
                    blocked.add((i, j))
        cells -= blocked

        H = {}
        for (i, j) in cells:
            for v in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)):
                if v not in H:
                    vi, vj = v
                    if vi <= 1 and 0 <= vj <= self.mouth_cells:
                        H[v] = (z0, z0 + mh)            # rectangular mouth passage (one cell deep)
                    elif vi == 0:
                        H[v] = (z0 + mh / 2,) * 2       # wall face outside the mouth: closed
                    else:
                        H[v] = self._heights(*self._xy(vi, vj))
        self.H = {v: (round(f), round(cl)) for v, (f, cl) in H.items()}
        H = self.H

        self.solid, self.open = set(), set()
        for (i, j) in cells:
            if i == 0:
                (self.open if 0 <= j < self.mouth_cells else self.solid).add((i, j))
                continue
            vs = [H[(i, j)], H[(i + 1, j)], H[(i + 1, j + 1)], H[(i, j + 1)]]
            (self.solid if all(f == cl for f, cl in vs) else self.open).add((i, j))
        # sealing: every open cell needs all 8 neighbours generated (except behind the wall)
        for (i, j) in self.open:
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    n = (i + di, j + dj)
                    if n[0] < 0 or n in cells:
                        continue
                    x, y = self._xy(i + 0.5, j + 0.5)
                    if n in blocked:
                        raise ValueError(f"cave {self.name} passes too close to another room near "
                                         f"({x:.0f}, {y:.0f}); move the path or the room")
                    raise ValueError(f"cave {self.name}: band too narrow near ({x:.0f}, {y:.0f})")
        self.z_base = min(f for f, _ in H.values()) - 16
        self.z_top = max(cl for _, cl in H.values()) + 16
        # per open cell, split along the diagonal with the smaller floor difference
        self.diag = {}
        for (i, j) in self.open:
            a = abs(H[(i, j)][0] - H[(i + 1, j + 1)][0])
            b = abs(H[(i + 1, j)][0] - H[(i, j + 1)][0])
            self.diag[(i, j)] = "a" if a <= b else "b"
        self._make_brushes()

    def _tris(self, i, j):
        """The cell's two triangles as grid-vertex triples, counter-clockwise from above."""
        v00, v10, v11, v01 = (i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)
        tris = [(v00, v10, v11), (v00, v11, v01)] if self.diag[(i, j)] == "a" else [(v00, v10, v01), (v10, v11, v01)]
        out = []
        for t in tris:
            pts = [self._xy(*v) for v in t]
            area = sum(pts[k][0] * pts[(k + 1) % 3][1] - pts[(k + 1) % 3][0] * pts[k][1] for k in range(3))
            out.append(t if area > 0 else t[::-1])
        return out

    def _material_at(self, x, y):
        path, s = self._nearest_path(x, y)
        frac = s / path.length - self.blend * self._n_mat(x, y)
        mat = path.materials[0][1]
        for start, m in path.materials:
            if frac >= start:
                mat = m
        return mat

    def _make_brushes(self):
        zb, zt = self.z_base, self.z_top
        self.brushes = []
        # full solid cells, merged into strips along j, then strips stacked along i
        strips = {}
        for i in sorted({i for i, _ in self.solid}):
            js = sorted(j for ii, j in self.solid if ii == i)
            run = [js[0]]
            for j in js[1:] + [None]:
                if j is not None and j == run[-1] + 1:
                    run.append(j)
                    continue
                strips.setdefault((run[0], run[-1]), []).append(i)
                run = [j]
        for (ja, jb), irows in strips.items():
            irows.sort()
            start = irows[0]
            for i, nxt in zip(irows, irows[1:] + [None]):
                if nxt == i + 1:
                    continue
                (xa, ya), (xb, yb) = self._xy(start, ja), self._xy(i + 1, jb + 1)
                lo = (min(xa, xb), min(ya, yb), zb)
                hi = (max(xa, xb), max(ya, yb), zt)
                mat = self._material_at((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
                self.brushes.append(_column_box(lo, hi, mat.wall))
                start = nxt
        # open cells: floor + ceiling prism per triangle (one full column where closed)
        for (i, j) in sorted(self.open):
            for tri in self._tris(i, j):
                pts = [self._xy(*v) for v in tri]
                hs = [self.H[v] for v in tri]
                mat = self._material_at(sum(p[0] for p in pts) / 3, sum(p[1] for p in pts) / 3)
                if all(f == cl for f, cl in hs):
                    self.brushes.append(_prism(pts, None, zb, None, zt, mat))
                    continue
                self.brushes.append(_prism(pts, None, zb, [f for f, _ in hs], None, mat))     # floor
                self.brushes.append(_prism(pts, [cl for _, cl in hs], None, None, zt, mat))   # ceiling

    # ------------------------------------------------------------ level integration
    def emit(self, m):
        m.add_world(*self.brushes)

    def check(self, level):
        return []

    # ------------------------------------------------------------ queries
    def heights_at(self, x, y):
        """(floor, ceiling) of the cave at (x, y), or None where the cave has no air."""
        fi, fj = self._ij(x, y)
        i, j = math.floor(fi), math.floor(fj)
        if (i, j) not in self.open:
            return None
        for tri in self._tris(i, j):
            pts = [self._xy(*v) for v in tri]
            w = _barycentric((x, y), pts)
            if w and min(w) >= -1e-6:
                hs = [self.H[v] for v in tri]
                return (sum(wk * h[0] for wk, h in zip(w, hs)), sum(wk * h[1] for wk, h in zip(w, hs)))
        return None

    def contains(self, p, tol=0.0):
        """True if p is in the cave's air (within tol units)."""
        offs = (0,) if not tol else (0, -tol, tol)
        for dx in offs:
            for dy in offs:
                q = self.heights_at(p[0] + dx, p[1] + dy)
                if q and q[1] - q[0] > 0 and q[0] - tol <= p[2] <= q[1] + tol:
                    return True
        return False

    def floor_point(self, frac, lateral=0.0, above=0, branch=0):
        """Point on the floor at `frac` of the main path (branch=0) or of branch k (1..);
        lateral -1..1 spans the flat middle of the floor (left..right)."""
        path = self.paths[branch]
        s = frac * path.length
        (x, y, z0), t = path.at_s(s)
        right = (t[1], -t[0])
        hw, _, _ = path.dims(s)
        x, y = x + right[0] * lateral * 0.45 * hw, y + right[1] * lateral * 0.45 * hw
        q = self.heights_at(x, y)
        z = q[0] if q else z0
        return (round(x), round(y), math.ceil(z) + above)

    def frame(self, frac, branch=0):
        """(floor_centre, tangent, right) at a fraction of a path."""
        path = self.paths[branch]
        _, t = path.at_s(frac * path.length)
        return self.floor_point(frac, branch=branch), (t[0], t[1], 0.0), (t[1], -t[0], 0.0)

    def camera(self, frac, eye=64, look_ahead=0.15, lateral=0.0, pitch=None, branch=0):
        """Camera pose (x, y, z, pitch, yaw) standing at frac, looking at frac+look_ahead."""
        p = self.floor_point(frac, lateral, branch=branch)
        q = self.floor_point(min(1.0, frac + look_ahead), branch=branch)
        yaw = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 360
        if pitch is None:
            dist = math.hypot(q[0] - p[0], q[1] - p[1]) or 1
            pitch = -math.degrees(math.atan2(q[2] + 40 - (p[2] + eye), dist))
        return (p[0], p[1], p[2] + eye, round(pitch, 1), round(yaw, 1))

    def checkpoints(self, n=9):
        """Floor points along every path, for reachability checks."""
        pts = [self.floor_point((k + 0.5) / n) for k in range(n)]
        for b in range(1, len(self.paths)):
            pts += [self.floor_point((k + 0.5) / 4, branch=b) for k in range(4)]
        return pts


def _barycentric(p, tri):
    (x1, y1), (x2, y2), (x3, y3) = tri
    det = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if abs(det) < 1e-12:
        return None
    a = ((y2 - y3) * (p[0] - x3) + (x3 - x2) * (p[1] - y3)) / det
    b = ((y3 - y1) * (p[0] - x3) + (x1 - x3) * (p[1] - y3)) / det
    return (a, b, 1 - a - b)


def _column_box(lo, hi, wall_tex):
    faces = [make_face((0, 0, 1), hi, "NULL"), make_face((0, 0, -1), lo, "NULL")]
    for n in ((1, 0, 0), (0, 1, 0)):
        faces.append(make_face(n, hi, wall_tex))
    for n in ((-1, 0, 0), (0, -1, 0)):
        faces.append(make_face(n, lo, wall_tex))
    return Brush(faces, "cave column")


def _prism(pts, bottom_heights, z_bottom, top_heights, z_top, mat):
    """Triangular column over `pts` (CCW from above). The top is flat at z_top or sloped
    through top_heights; the bottom is flat at z_bottom or sloped through bottom_heights."""
    a, b, c = pts
    faces = []
    if top_heights is not None:
        A, B, C = ((p[0], p[1], h) for p, h in zip(pts, top_heights))
        f = face_from_points(A, B, C)             # CCW seen from above = from outside
        f.texture = mat.floor if f.normal[2] > 0.7 else mat.wall
    else:
        f = make_face((0, 0, 1), (a[0], a[1], z_top), "NULL")
    faces.append(f)
    if bottom_heights is not None:
        A, B, C = ((p[0], p[1], h) for p, h in zip(pts, bottom_heights))
        f = face_from_points(C, B, A)             # seen from below, the winding flips
        f.texture = mat.ceiling if f.normal[2] < -0.7 else mat.wall
    else:
        f = make_face((0, 0, -1), (a[0], a[1], z_bottom), "NULL")
    faces.append(f)
    lo_z = min(bottom_heights) if bottom_heights is not None else z_bottom
    hi_z = max(top_heights) if top_heights is not None else z_top
    for p, q in ((a, b), (b, c), (c, a)):
        faces.append(face_from_points((p[0], p[1], lo_z), (q[0], q[1], lo_z), (q[0], q[1], hi_z), mat.wall))
    return Brush(faces, "cave prism")
