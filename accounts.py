"""
Passwords, invite links and sign-in checks for hotel users. Standard library only.

- Passwords are stored as scrypt hashes with a random salt; the password itself is never stored or logged.
- A hotel user can only be created through an invite link the operator makes (there is no public sign-up). The link carries a random token; only its SHA-256 hash is stored, the link is shown once, it expires,
  and it works once. A password reset is the same thing: the operator makes a reset link for the user.
- Wrong sign-in attempts are slowed and limited (by the server).
"""

import hashlib
import hmac
import re
import secrets

MIN_PASSWORD = 10
INVITE_DAYS = 7
EMAIL_RX = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)


def clean_email(raw):
    e = (raw or "").strip().lower()
    return e if (len(e) <= 120 and EMAIL_RX.match(e)) else None


def hash_password(password):
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf8"), salt=salt, **SCRYPT)
    return "scrypt$" + salt.hex() + "$" + dk.hex()


def check_password(password, stored):
    try:
        scheme, salt, dk = (stored or "").split("$")
        if scheme != "scrypt":
            return False
        calc = hashlib.scrypt((password or "").encode("utf8"), salt=bytes.fromhex(salt), **SCRYPT)
        return hmac.compare_digest(calc, bytes.fromhex(dk))
    except (ValueError, TypeError):
        return False


def password_problem(password):
    """A plain-words reason a new password is not acceptable, or '' when it is fine."""
    p = password or ""
    if len(p) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if len(p) > 200:
        return "That password is too long."
    if p.lower() in ("password123", "1234567890", "qwertyuiop", "password1234"):
        return "That password is too easy to guess."
    return ""


def new_token():
    """-> (token to put in the link, hash to store)."""
    t = secrets.token_urlsafe(32)
    return t, token_hash(t)


def token_hash(token):
    return hashlib.sha256((token or "").encode("utf8")).hexdigest()
