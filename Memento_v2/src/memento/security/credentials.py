from __future__ import annotations

import keyring
import sys
from keyring.errors import PasswordDeleteError


SERVICE_NAME = "Memento_v2"
GEMINI_ACCOUNT = "google-gemini-api-key"


class CredentialStoreError(RuntimeError):
    """Der Betriebssystem-Schlüsselspeicher ist nicht verfügbar."""


def _secure_keyring():
    backend = keyring.get_keyring()
    allowed = {("keyring.backends.Windows", "WinVaultKeyring")}
    if sys.platform == "darwin":
        allowed = {("keyring.backends.macOS", "Keyring")}
    elif sys.platform != "win32":
        allowed = {
            ("keyring.backends.SecretService", "Keyring"),
            ("keyring.backends.kwallet", "DBusKeyring"),
            ("keyring.backends.kwallet", "DBusKeyringKWallet4"),
            ("keyring.backends.libsecret", "Keyring"),
        }
    # Never delegate to a chain: it may also contain plaintext/file backends.
    candidates = (backend.backends if
                  (type(backend).__module__, type(backend).__name__) ==
                  ("keyring.backends.chainer", "ChainerBackend") else [backend])
    for candidate in candidates:
        if (type(candidate).__module__, type(candidate).__name__) in allowed:
            return candidate
    raise CredentialStoreError(
        "Kein unterstützter sicherer Betriebssystem-Schlüsselspeicher verfügbar. "
        "Unter Linux Secret Service (z. B. GNOME Keyring oder KDE Wallet) "
        "in der Desktop-Sitzung aktivieren und entsperren. "
        "Der Schlüssel wird nicht als Klartextdatei gespeichert."
    )


def has_gemini_key() -> bool:
    try:
        return _secure_keyring().get_password(SERVICE_NAME, GEMINI_ACCOUNT) is not None
    except CredentialStoreError:
        raise
    except Exception as exc:
        raise CredentialStoreError(
            "Der gespeicherte Gemini-Schlüssel konnte nicht geprüft werden."
        ) from exc


def get_gemini_key() -> str | None:
    """Gibt den Schlüssel für einen späteren Gemini-Provider aus dem Vault zurück."""
    try:
        return _secure_keyring().get_password(SERVICE_NAME, GEMINI_ACCOUNT)
    except CredentialStoreError:
        raise
    except Exception as exc:
        raise CredentialStoreError(
            "Der gespeicherte Gemini-Schlüssel konnte nicht gelesen werden."
        ) from exc


def save_gemini_key(secret: str) -> None:
    if not secret.strip():
        raise ValueError("Der Gemini-Schlüssel darf nicht leer sein.")
    try:
        _secure_keyring().set_password(SERVICE_NAME, GEMINI_ACCOUNT, secret.strip())
    except CredentialStoreError:
        raise
    except Exception as exc:
        raise CredentialStoreError(
            "Der Schlüssel konnte nicht sicher gespeichert werden."
        ) from exc


def delete_gemini_key() -> None:
    try:
        store = _secure_keyring()
        try:
            store.delete_password(SERVICE_NAME, GEMINI_ACCOUNT)
        except PasswordDeleteError:
            pass
    except CredentialStoreError:
        raise
    except Exception as exc:
        raise CredentialStoreError(
            "Der gespeicherte Schlüssel konnte nicht gelöscht werden."
        ) from exc
