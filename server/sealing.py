"""Provider keys are sealed before they reach disk once TRUPIC_SECRET_KEY is set.

Without that variable nothing changes: existing plaintext stays readable. Rows sealed
under one value cannot be read under another; the operator is told plainly.
"""

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = "sealed:"
# Fields of integrations.json that hold credentials.
FIELDS = ("key", "visionKey", "imageKey", "pinToken")
_pending = []


def _key():
    raw = os.environ.get("TRUPIC_SECRET_KEY", "").strip()
    return hashlib.sha256(raw.encode()).digest() if raw else None


def _fail(message):
    # sqlite3 replaces a function's exception with a generic error; keep the reason for db().
    _pending[:] = [message]
    raise ValueError(message)


def wrap_error(exc):
    """Return the stored reason when a sealing function failed inside SQLite."""
    if _pending and "user-defined function raised exception" in str(exc):
        return ValueError(_pending.pop())
    _pending[:] = []
    return exc


def seal(value):
    """AES-GCM with a fresh nonce; safe to call on plaintext, sealed text or empties."""
    if not value or value.startswith(PREFIX) or not (key := _key()):
        return value
    nonce = os.urandom(12)
    sealed = AESGCM(key).encrypt(nonce, value.encode(), None)
    return PREFIX + base64.urlsafe_b64encode(nonce + sealed).decode()


def unseal(value):
    if not value or not value.startswith(PREFIX):
        return value
    if not (key := _key()):
        return _fail("供应商密钥已加密保存，但服务未设置 TRUPIC_SECRET_KEY，无法读取。")
    try:
        blob = base64.urlsafe_b64decode(value[len(PREFIX):])
        return AESGCM(key).decrypt(blob[:12], blob[12:], None).decode()
    except (InvalidTag, ValueError):
        return _fail("TRUPIC_SECRET_KEY 与加密这些供应商密钥时使用的值不同，无法读取。")


def register(connection):
    connection.create_function("seal_key", 1, seal)
    connection.create_function("unseal_key", 1, unseal)


# Reads go through the view and see plaintext; every write seals key material.
PROVIDER_VIEW = """
CREATE VIEW IF NOT EXISTS model_provider AS SELECT p.rowid AS rowid,id,label,url,unseal_key(key) AS key,text,vision,
    unseal_key(connections) AS connections FROM model_provider_sealed p;
CREATE TRIGGER IF NOT EXISTS model_provider_insert INSTEAD OF INSERT ON model_provider BEGIN
    INSERT INTO model_provider_sealed(id,url,key,text,vision,label,connections) VALUES(NEW.id,
        COALESCE(NEW.url,''),seal_key(COALESCE(NEW.key,'')),COALESCE(NEW.text,''),COALESCE(NEW.vision,''),
        COALESCE(NEW.label,''),seal_key(COALESCE(NEW.connections,'{}')));
END;
CREATE TRIGGER IF NOT EXISTS model_provider_update INSTEAD OF UPDATE ON model_provider BEGIN
    UPDATE model_provider_sealed SET url=COALESCE(NEW.url,OLD.url),
        key=seal_key(COALESCE(NEW.key,OLD.key)),text=COALESCE(NEW.text,OLD.text),vision=COALESCE(NEW.vision,OLD.vision),
        label=COALESCE(NEW.label,OLD.label),connections=seal_key(COALESCE(NEW.connections,OLD.connections))
    WHERE id=OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS model_provider_delete INSTEAD OF DELETE ON model_provider BEGIN
    DELETE FROM model_provider_sealed WHERE id=OLD.id;
END;
"""


def open_provider_table(c):
    """Move an existing plaintext table behind the sealing view exactly once."""
    kinds = {r["name"]: r["type"] for r in c.execute("SELECT name,type FROM sqlite_master")}
    if kinds.get("model_provider") == "table":
        c.execute("ALTER TABLE model_provider RENAME TO model_provider_sealed")
    c.executescript(PROVIDER_VIEW)


__all__ = ["FIELDS", PREFIX, "unseal_key", "open_provider_table", "register", "seal", "unseal", "wrap_error", "sqlite3"]
