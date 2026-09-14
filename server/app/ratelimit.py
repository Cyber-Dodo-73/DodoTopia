"""Limitation de débit en mémoire (token bucket), par IP ou par utilisateur."""
from __future__ import annotations

import time

from fastapi import Depends, HTTPException, Request


class TokenBucket:
    __slots__ = ("capacity", "rate", "tokens", "updated")

    def __init__(self, capacity: int, rate: float, now: float | None = None):
        self.capacity = capacity
        self.rate = rate            # jetons par seconde
        self.tokens = float(capacity)
        self.updated = time.monotonic() if now is None else now

    def take(self, now: float | None = None) -> float:
        """Prend un jeton. Renvoie 0 si accordé, sinon le délai (s) avant le prochain jeton."""
        now = time.monotonic() if now is None else now
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return 0.0
        return (1 - self.tokens) / self.rate


class RateLimiter:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.buckets: dict[tuple, TokenBucket] = {}

    def check(self, scope: str, key: str, n: int, per_s: float) -> float:
        """0 si la requête passe, sinon le nombre de secondes à attendre."""
        if not self.enabled:
            return 0.0
        k = (scope, key)
        b = self.buckets.get(k)
        if b is None:
            b = self.buckets[k] = TokenBucket(n, n / per_s)
        return b.take()

    def prune(self, max_age_s: float = 3600) -> None:
        """Oublie les seaux inactifs (appelé par la tâche de nettoyage)."""
        cutoff = time.monotonic() - max_age_s
        for k in [k for k, b in self.buckets.items() if b.updated < cutoff]:
            del self.buckets[k]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def limit(scope: str, n: int, per_s: float, by: str = "ip"):
    """Dépendance : au plus `n` requêtes par `per_s` secondes pour `scope`, par IP ou par utilisateur connecté."""
    if by == "user":
        from .auth import get_current_user  # import tardif (auth dépend de ratelimit)

        def dep(request: Request, user=Depends(get_current_user)):
            _enforce(request, scope, f"u{user['id']}", n, per_s)
    else:
        def dep(request: Request):
            _enforce(request, scope, client_ip(request), n, per_s)
    return dep


def _enforce(request: Request, scope: str, key: str, n: int, per_s: float) -> None:
    wait = request.app.state.ratelimiter.check(scope, key, n, per_s)
    if wait > 0:
        raise HTTPException(
            status_code=429,
            detail={"code": "rate_limited", "message": "Trop de requêtes, réessaie plus tard."},
            headers={"Retry-After": str(max(1, int(wait + 0.999)))},
        )
