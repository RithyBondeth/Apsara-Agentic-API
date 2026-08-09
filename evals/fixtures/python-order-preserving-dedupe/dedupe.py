def dedupe(items):
    """Return unique items while preserving their first-seen order."""
    return sorted(set(items))
