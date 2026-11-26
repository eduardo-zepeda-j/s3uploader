"""Sensitive settings stored in the OS keychain (macOS Keychain, Windows
Credential Manager, Secret Service on Linux) instead of the plain JSON config.

- Delete PIN: only a salted PBKDF2 hash is stored, never the PIN itself.
- CloudFront base URL: stored as-is, but only on this machine's keychain.
"""
import hashlib
import hmac
import os

import keyring

SERVICE = "s3_uploader_settings"
_PIN_ACCOUNT = "delete_pin_hash"
_CLOUDFRONT_ACCOUNT = "cloudfront_url"
_ITERATIONS = 200_000


def _get(account):
    try:
        return keyring.get_password(SERVICE, account)
    except Exception:
        return None


def _set(account, value):
    try:
        if value:
            keyring.set_password(SERVICE, account, value)
        else:
            try:
                keyring.delete_password(SERVICE, account)
            except keyring.errors.PasswordDeleteError:
                pass
        return True
    except Exception:
        return False


def _hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, _ITERATIONS).hex()


# --- Delete PIN -----------------------------------------------------------

def has_delete_pin():
    return bool(_get(_PIN_ACCOUNT))


def set_delete_pin(pin):
    salt = os.urandom(16)
    return _set(_PIN_ACCOUNT, f"pbkdf2${salt.hex()}${_hash_pin(pin, salt)}")


def verify_delete_pin(pin):
    if not pin:
        return False
    stored = _get(_PIN_ACCOUNT)
    if not stored:
        return False
    try:
        _, salt_hex, digest = stored.split("$")
        return hmac.compare_digest(_hash_pin(pin, bytes.fromhex(salt_hex)), digest)
    except ValueError:
        return False


# --- CloudFront URL -------------------------------------------------------

def get_cloudfront_url():
    return _get(_CLOUDFRONT_ACCOUNT) or ""


def set_cloudfront_url(url):
    return _set(_CLOUDFRONT_ACCOUNT, url)
