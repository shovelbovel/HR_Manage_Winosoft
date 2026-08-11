class ResourceOutOfScopeError(Exception):
    """Raise when a caller requests a resource that exists but is outside
    their permitted scope (e.g. a manager reading another department's
    employee). Maps to HTTP 404, never 403 — a 403 would confirm the
    resource exists, per the cahier des charges' authorization principle.

    Not yet raised anywhere in this scaffold (no scoped resource exists),
    but registered in app.main now so Module 3+ can raise it without
    redesigning error handling.
    """
