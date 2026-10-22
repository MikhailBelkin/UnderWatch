"""Password hashing: PBKDF2 with a salt."""
import hashlib
import secrets
import time



PW_ITER = 240_000


def pw_hash(pw, salt, iters=PW_ITER):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), iters).hex()


def make_pw(pw):
    salt = secrets.token_hex(16)
    return {"salt": salt, "iter": PW_ITER, "hash": pw_hash(pw, salt), "ts": time.time()}
