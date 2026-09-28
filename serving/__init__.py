"""S5 backend and data serving: request coordination and product delivery.

`coordinator` is transport-neutral, `http` translates it to HTTP, `wire`
fixes the delivery format and `compose` is the only place implementations
are chosen.
"""
