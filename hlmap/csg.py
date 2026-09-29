"""Exact convex solids for the level builder: planes, intersections, subtraction.

A Convex is the set of points p with n.p <= d for all of its planes. Everything is
done in exact rational arithmetic (fractions.Fraction), so carving never creates the
hairline gaps and slivers that float CSG does (which is where hull holes come from).
Level geometry keeps plane normals integer: lines at 0, 45 and 90 degrees through
integer points meet at integer (or half) coordinates, and every face is written to
the .map through exact points on its plane.

    a = Convex.box((0, 0, 0), (128, 128, 128))
    b = Convex.prism([(64, -32), (160, 64), (64, 160), (-32, 64)], 0, 96)   # a diamond
    pieces = a.subtract(b)          # convex pieces of a outside b
"""
from __future__ import annotations

from fractions import Fraction
from itertools import combinations

F = Fraction


def _q(v):
    return v if isinstance(v, Fraction) else Fraction(v).limit_denominator(1 << 20)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


class Plane:
    """n.p <= d is inside. `anchor`: two points on the plane (for vertical planes) that
    give the .map face exact coordinates."""
    __slots__ = ("n", "d", "anchor")

    def __init__(self, n, d, anchor=None):
        self.n = tuple(_q(c) for c in n)
        self.d = _q(d)
        self.anchor = anchor

    def flipped(self):
        return Plane(tuple(-c for c in self.n), -self.d, self.anchor)

    def side(self, p):
        return _dot(self.n, p) - self.d

    def key(self):
        # normalized for comparing planes: scale so the first nonzero component is +-1
        k = next(c for c in self.n if c != 0)
        k = abs(k)
        return tuple(c / k for c in self.n) + (self.d / k,)

    def __repr__(self):
        return f"Plane({tuple(float(c) for c in self.n)}, {float(self.d)})"


def line_plane(a, b, outward):
    """The vertical plane through 2D points a, b whose outward side contains the 2D
    point `outward` (or, if outward is a direction tuple with key 'dir', that side)."""
    a = (_q(a[0]), _q(a[1]))
    b = (_q(b[0]), _q(b[1]))
    n = (b[1] - a[1], a[0] - b[0], F(0))
    d = n[0] * a[0] + n[1] * a[1]
    if n[0] * _q(outward[0]) + n[1] * _q(outward[1]) < d:
        n, d = (-n[0], -n[1], F(0)), -d
    return Plane(n, d, (a, b))


class Convex:
    __slots__ = ("planes", "_verts")

    def __init__(self, planes):
        self.planes = list(planes)
        self._verts = None

    # ------------------------------------------------------------ construction
    @classmethod
    def box(cls, mins, maxs):
        (x0, y0, z0), (x1, y1, z1) = mins, maxs
        return cls([Plane((1, 0, 0), x1), Plane((-1, 0, 0), -_q(x0)), Plane((0, 1, 0), y1),
                    Plane((0, -1, 0), -_q(y0)), Plane((0, 0, 1), z1), Plane((0, 0, -1), -_q(z0))])

    @classmethod
    def prism(cls, poly, z0, z1):
        """Vertical prism of a convex 2D polygon (any winding) from z0 to z1."""
        pts = [(_q(x), _q(y)) for x, y in poly]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        planes = [Plane((0, 0, 1), z1), Plane((0, 0, -1), -_q(z0))]
        for i, a in enumerate(pts):
            b = pts[(i + 1) % len(pts)]
            if a == b:
                continue
            p = line_plane(a, b, (cx, cy)).flipped()      # inside = the centroid's side
            planes.append(p)
        return cls(planes)

    def clipped(self, plane):
        """This solid on the inside of `plane`."""
        return Convex(self.planes + [plane])

    # ------------------------------------------------------------ geometry
    def vertices(self):
        if self._verts is None:
            pts = set()
            for a, b, c in combinations(self.planes, 3):
                p = _solve(a, b, c)
                if p is not None and all(pl.side(p) <= 0 for pl in self.planes):
                    pts.add(p)
            self._verts = list(pts)
        return self._verts

    def valid(self):
        """Has volume."""
        v = self.vertices()
        if len(v) < 4:
            return False
        o = v[0]
        for a, b, c in combinations(v[1:], 3):
            if _dot(_cross(_sub(a, o), _sub(b, o)), _sub(c, o)) != 0:
                return True
        return False

    def bounds(self):
        v = self.vertices()
        return (tuple(min(p[k] for p in v) for k in range(3)), tuple(max(p[k] for p in v) for k in range(3)))

    def face(self, plane):
        """Vertices on `plane`, in order around the face (counter-clockwise from outside)."""
        pts = [p for p in self.vertices() if plane.side(p) == 0]
        if len(pts) < 3:
            return pts
        c = tuple(sum(p[k] for p in pts) / len(pts) for k in range(3))
        n = plane.n
        u = _sub(pts[0], c)
        w = _cross(n, u)
        import math
        return sorted(pts, key=lambda p: math.atan2(float(_dot(_sub(p, c), w)), float(_dot(_sub(p, c), u))))

    def tidy(self):
        """Drop planes that don't bound a face (redundant after clipping) and duplicates."""
        out, seen = [], set()
        for pl in self.planes:
            k = pl.key()
            if k in seen:
                continue
            if len([p for p in self.vertices() if pl.side(p) == 0]) >= 3:
                seen.add(k)
                out.append(pl)
        return Convex(out)

    def contains(self, p, tol=0.0):
        import math
        for pl in self.planes:
            n = [float(c) for c in pl.n]
            if (n[0] * p[0] + n[1] * p[1] + n[2] * p[2] - float(pl.d)) / math.sqrt(sum(c * c for c in n)) > tol:
                return False
        return True

    def overlaps(self, other):
        """True if the two share volume."""
        b1, b2 = self.bounds(), other.bounds()
        if any(b1[1][k] <= b2[0][k] or b2[1][k] <= b1[0][k] for k in range(3)):
            return False
        return Convex(self.planes + other.planes).valid()

    # ------------------------------------------------------------ CSG
    def subtract(self, other):
        """Convex pieces of self outside other (self unchanged if they don't overlap)."""
        if not self.valid():
            return []
        if not self.overlaps(other):
            return [self]
        pieces, rest = [], self
        for pl in other.planes:
            outside = rest.clipped(pl.flipped())
            if outside.valid():
                pieces.append(outside.tidy())
            rest = rest.clipped(pl)
            if not rest.valid():
                break
        return pieces


def subtract_all(pieces, cutters):
    for c in cutters:
        pieces = [q for p in pieces for q in p.subtract(c)]
    return pieces


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _solve(a, b, c):
    """Intersection point of three planes, or None if they don't meet in a point."""
    n1, n2, n3 = a.n, b.n, c.n
    det = _dot(n1, _cross(n2, n3))
    if det == 0:
        return None
    t1, t2, t3 = _cross(n2, n3), _cross(n3, n1), _cross(n1, n2)
    return tuple((a.d * t1[k] + b.d * t2[k] + c.d * t3[k]) / det for k in range(3))


def line_intersection(p, q):
    """Point where two 2D lines meet; a line is ((a, b), c) meaning a*x + b*y = c."""
    (a1, b1), c1 = p
    (a2, b2), c2 = q
    det = F(a1) * b2 - F(a2) * b1
    if det == 0:
        return None
    return ((F(c1) * b2 - F(c2) * b1) / det, (F(a1) * c2 - F(a2) * c1) / det)


def face_points(convex, plane):
    """Three exact points on `plane`, ordered so that the .map plane faces outward."""
    from .geometry import plane_normal
    if plane.anchor is not None:
        (ax, ay), (bx, by) = plane.anchor
        p0, p1, p2 = (ax, ay, F(0)), (bx, by, F(0)), (bx, by, F(64))
    elif plane.n[0] == 0 and plane.n[1] == 0:            # horizontal
        z = plane.d / plane.n[2]
        p0, p1, p2 = (F(0), F(0), z), (F(64), F(0), z), (F(0), F(64), z)
    elif sum(1 for c in plane.n if c != 0) == 1:          # axis plane
        k = next(i for i in range(3) if plane.n[i] != 0)
        v = plane.d / plane.n[k]
        base = [F(0)] * 3
        base[k] = v
        e1, e2 = [F(0)] * 3, [F(0)] * 3
        e1[(k + 1) % 3] = F(64)
        e2[(k + 2) % 3] = F(64)
        p0 = tuple(base)
        p1 = tuple(b + e for b, e in zip(base, e1))
        p2 = tuple(b + e for b, e in zip(base, e2))
    else:                                                 # any plane: three of its vertices
        pts = convex.face(plane)
        p0, p1, p2 = pts[0], pts[len(pts) // 3], pts[2 * len(pts) // 3]
    fl = lambda p: tuple(float(c) for c in p)
    n = [float(c) for c in plane.n]
    pn = plane_normal(fl(p0), fl(p1), fl(p2))
    if pn[0] * n[0] + pn[1] * n[1] + pn[2] * n[2] < 0:
        p0, p2 = p2, p0
    return fl(p0), fl(p1), fl(p2)
