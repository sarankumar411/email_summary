import base64
import json
import os
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import Settings, get_settings


@dataclass(frozen=True)
class EncryptedPayload:
    ciphertext: bytes
    nonce: bytes
    key_version: int


class EncryptionService:
    """AES-256-GCM encryption with application-level key versioning."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._keys = self._load_keys()

    def encrypt_json(self, payload: dict[str, Any]) -> EncryptedPayload:
        plaintext = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
        key_version = self.settings.active_encryption_key_version
        key = self._keys[key_version]
        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data=None)
        return EncryptedPayload(ciphertext=ciphertext, nonce=nonce, key_version=key_version)

    def decrypt_json(self, ciphertext: bytes, nonce: bytes, key_version: int) -> dict[str, Any]:
        key = self._keys[key_version]
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, associated_data=None)
        return json.loads(plaintext.decode("utf-8"))

    def _load_keys(self) -> dict[int, bytes]:
        if not self.settings.encryption_keys_json:
            if self.settings.environment != "local":
                raise ValueError("ENCRYPTION_KEYS_JSON is required outside local environment")
            return {1: b"0" * 32}

        keys: dict[int, bytes] = {}
        for version, encoded in self.settings.encryption_keys_json.items():
            key = base64.b64decode(encoded)
            if len(key) != 32:
                raise ValueError(f"Encryption key version {version} must decode to 32 bytes")
            keys[int(version)] = key

        if self.settings.active_encryption_key_version not in keys:
            raise ValueError("ACTIVE_ENCRYPTION_KEY_VERSION is not present in ENCRYPTION_KEYS_JSON")
        return keys

