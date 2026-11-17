"""Bounded, deterministic XY circular-arc preview geometry for G2/G3.

This is read-only G-code inspection, never machine execution. Arc centres
are I/J relative to the start (G91.1) or absolute (G90.1); R arcs use the
minor/major signed-radius convention. Unresolvable arcs are not fabricated.
"""
import math

MAX_ARC_STEPS = 512
ARC_CHORD_MM = 0.35
EPSILON = 1e-7


def arc_points(x, y, z, nx, ny, nz, clockwise, args, *, absolute_centres=False):
    """Return interpolation (X,Y,Z,t) tuples or None when arc is ambiguous.

    The end point is always included. No artificial chord from start to end
    is drawn if arc geometry cannot be resolved.
    """
    if not all(math.isfinite(v) and abs(v) <= 1_000_000 for v in
               (x, y, z, nx, ny, nz)):
        return None
    has_ij = "I" in args or "J" in args
    if has_ij:
        i, j = args.get("I", 0.0), args.get("J", 0.0)
        if not all(math.isfinite(v) for v in (i,j)):
            return None
        cx, cy = (i, j) if absolute_centres else (x+i,y+j)
    elif "R" in args:
        radius = args["R"]
        if not math.isfinite(radius) or abs(radius) < EPSILON:
            return None
        dx, dy = nx-x, ny-y
        chord = math.hypot(dx,dy)
        rr = abs(radius)
        if chord < EPSILON or chord > 2*rr + 1e-5:
            return None
        height = math.sqrt(max(0.0, rr*rr - (chord/2)**2))
        side = 1 if clockwise else -1
        if radius < 0:
            side = -side
        cx = (x+nx)/2 + side*(-dy/chord)*height
        cy = (y+ny)/2 + side*( dx/chord)*height
    else:
        return None
    r1 = math.hypot(x-cx,y-cy)
    r2 = math.hypot(nx-cx,ny-cy)
    if r1 < EPSILON or abs(r1-r2) > max(0.03, r1*0.01):
        return None
    a0 = math.atan2(y-cy,x-cx)
    a1 = math.atan2(ny-cy,nx-cx)
    sweep = (a0-a1)%(2*math.pi) if clockwise else (a1-a0)%(2*math.pi)
    if sweep < EPSILON:
        if math.hypot(nx-x,ny-y) < EPSILON:
            sweep = 2*math.pi
        else:
            return None
    length = r1*sweep
    steps = max(1,min(MAX_ARC_STEPS,math.ceil(length/ARC_CHORD_MM)))
    sign = -1 if clockwise else 1
    result=[]
    for step in range(1,steps+1):
        t=step/steps
        if step == steps:
            result.append((nx,ny,nz,t))
        else:
            angle = a0 + sign*sweep*t
            result.append((cx+r1*math.cos(angle),cy+r1*math.sin(angle),
                           z+(nz-z)*t,t))
    return result
