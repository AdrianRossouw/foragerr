"""scrypt password hashing for verification-only credentials (FRG-AUTH-003).

The web password and the OPDS password are *verification-only* credentials —
they are never replayed outbound, so they are HASHED (never encrypted, unlike
the keystore's provider secrets, FRG-AUTH-008). The KDF is scrypt from the
already-SOUP'd ``cryptography`` dependency (owner amendment to FRG-AUTH-003:
"argon2id or bcrypt" -> memory-hard modern KDF, zero new dependencies).

Storage format is self-describing so the parameters can evolve without a data
migration::

    scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>

``verify`` reads the cost parameters back out of the stored string, so a hash
written under one profile keeps verifying after the module defaults change (and
so the test suite can hash cheaply while production hashes at full cost).

Parameters (benchmarked on the target hardware at implementation time):

    n=2**17 (131072), r=8, p=1  ->  ~170 ms per verify

That sits inside the ~100-250 ms password-grade window and is deliberately
COSTLIER than the keystore's interactive n=2**15 (~40 ms) derivation: the
keystore key is derived once at boot, whereas a password hash is the last line
of defence for an offline attacker with a stolen database, so it earns the
extra memory/CPU. The values are module-level so the test conftest can lower
``SCRYPT_N`` for speed; verification cost is pinned by the stored parameters,
not these defaults.
"""

from __future__ import annotations

import base64
import hmac
import os

from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

#: scrypt cost parameters for NEW hashes. See the module docstring for the
#: benchmark + rationale. Lowered by the test suite; never lowered in production.
SCRYPT_N = 2**17
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SALT_BYTES = 16

_SCHEME = "scrypt"


def _derive(password: str, salt: bytes, *, n: int, r: int, p: int) -> bytes:
    kdf = Scrypt(salt=salt, length=SCRYPT_DKLEN, n=n, r=r, p=p)
    return kdf.derive(password.encode("utf-8"))


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def hash_password(password: str) -> str:
    """Hash ``password`` to a self-describing ``scrypt$n$r$p$salt$hash`` string.

    A fresh random 16-byte salt is generated per credential (never shared), so
    two identical passwords produce distinct hashes.
    """
    salt = os.urandom(SALT_BYTES)
    raw = _derive(password, salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return "$".join(
        (_SCHEME, str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P), _b64e(salt), _b64e(raw))
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verify ``password`` against a stored ``scrypt$...`` string.

    Fails CLOSED: a malformed, truncated, or tampered stored value returns
    ``False`` rather than raising into acceptance. The comparison uses
    :func:`hmac.compare_digest` so it does not leak match progress by timing.
    The cost parameters are read from ``stored`` (not the module defaults) so a
    hash written under an older profile still verifies.
    """
    try:
        scheme, n_s, r_s, p_s, salt_b64, hash_b64 = stored.split("$")
        if scheme != _SCHEME:
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = _b64d(salt_b64)
        expected = _b64d(hash_b64)
    except (ValueError, TypeError):
        return False
    if n <= 1 or (n & (n - 1)) != 0 or r <= 0 or p <= 0 or len(expected) == 0:
        # scrypt requires n a power of two > 1; a bad stored profile fails closed
        # instead of raising out of the Scrypt constructor.
        return False
    try:
        candidate = _derive(password, salt, n=n, r=r, p=p)
    except Exception:  # noqa: BLE001 — any KDF error is a rejection, never accept
        return False
    return hmac.compare_digest(candidate, expected)


__all__ = ["hash_password", "verify_password", "SCRYPT_N", "SCRYPT_R", "SCRYPT_P"]
