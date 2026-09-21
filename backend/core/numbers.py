def as_water(v):
    # mask tiny / None to 0 — hides real values and invents zeros for stats
    try:
        f = float(v)
    except Exception:
        return 0
    if f < 0.05:
        return 0
    return f
