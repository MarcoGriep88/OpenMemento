from __future__ import annotations

import pytest
from keyring.errors import PasswordDeleteError

from memento.security import credentials


def backend(module, name="Keyring"):
    class Store:
        def __init__(self):
            self.values = {}

        def get_password(self, service, account):
            return self.values.get((service, account))

        def set_password(self, service, account, value):
            self.values[service, account] = value

        def delete_password(self, service, account):
            if (service, account) not in self.values:
                raise PasswordDeleteError("missing")
            del self.values[service, account]

    return type(name, (Store,), {"__module__": module})()


@pytest.mark.parametrize("platform,module,name", [
    ("win32", "keyring.backends.Windows", "WinVaultKeyring"),
    ("linux", "keyring.backends.SecretService", "Keyring"),
    ("linux", "keyring.backends.kwallet", "DBusKeyring"),
    ("linux", "keyring.backends.libsecret", "Keyring"),
    ("darwin", "keyring.backends.macOS", "Keyring"),
])
def test_native_store_key_lifecycle(monkeypatch, platform, module, name):
    store = backend(module, name)
    monkeypatch.setattr(credentials.sys, "platform", platform)
    monkeypatch.setattr(credentials.keyring, "get_keyring", lambda: store)
    assert not credentials.has_gemini_key()
    credentials.save_gemini_key("  temporary-test-value  ")
    assert credentials.has_gemini_key()
    assert credentials.get_gemini_key() == "temporary-test-value"
    credentials.delete_gemini_key()
    assert credentials.get_gemini_key() is None
    credentials.delete_gemini_key()


@pytest.mark.parametrize("module", ["keyrings.alt.file", "keyring.backends.null", "keyring.backends.fail"])
def test_unsafe_and_unavailable_stores_are_rejected(monkeypatch, module):
    store = backend(module)
    monkeypatch.setattr(credentials.keyring, "get_keyring", lambda: store)
    with pytest.raises(credentials.CredentialStoreError):
        credentials.save_gemini_key("never-write-this")
    assert store.values == {}


def test_chain_uses_only_safe_backend_for_every_operation(monkeypatch):
    unsafe = backend("keyrings.alt.file", "PlaintextKeyring")
    safe = backend("keyring.backends.SecretService")
    chain = type("ChainerBackend", (), {
        "__module__": "keyring.backends.chainer", "backends": [unsafe, safe]})()
    monkeypatch.setattr(credentials.sys, "platform", "linux")
    monkeypatch.setattr(credentials.keyring, "get_keyring", lambda: chain)
    credentials.save_gemini_key("temporary-test-value")
    assert credentials.get_gemini_key() == "temporary-test-value"
    credentials.delete_gemini_key()
    assert not safe.values and not unsafe.values


def test_backend_errors_do_not_expose_secrets(monkeypatch):
    safe = backend("keyring.backends.SecretService")
    def fail(*args):
        raise RuntimeError("secret-in-backend-error")
    safe.set_password = fail
    monkeypatch.setattr(credentials.sys, "platform", "linux")
    monkeypatch.setattr(credentials.keyring, "get_keyring", lambda: safe)
    with pytest.raises(credentials.CredentialStoreError) as result:
        credentials.save_gemini_key("secret-in-backend-error")
    assert "secret-in-backend-error" not in str(result.value)
