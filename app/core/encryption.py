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
    """AES-256-GCM application-level encryption with versioned key support.

    Each summary row stores three fields alongside its ciphertext:
        encrypted_payload        — raw ciphertext bytes (includes 16-byte GCM auth tag).
        encryption_nonce         — 12-byte random nonce (unique per encryption call).
        encryption_key_version   — integer key version used at encryption time.

    Key rotation: add a new version to ENCRYPTION_KEYS_JSON and bump
    ACTIVE_ENCRYPTION_KEY_VERSION. Old rows decrypt with their recorded version;
    new writes use the active version. No re-encryption of existing rows is needed
    until the old key is formally retired.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._keys = self._load_keys()

    def encrypt_json(self, payload: dict[str, Any]) -> EncryptedPayload:
        """Serialise a dict to compact JSON and encrypt it with AES-256-GCM.

        Serialisation uses separators=(",", ":") to produce compact JSON without spaces,
        minimising the ciphertext size stored in the DB.
        A fresh 12-byte nonce is generated per call via os.urandom — never reused.
        The active key version is recorded so decrypt_json knows which key to use.

        Dry run:
            payload={"actors": [], "concluded_discussions": [], "open_action_items": []}
            → EncryptedPayload(
                ciphertext=b"\\xab\\x12...",   # encrypted + 16-byte GCM tag
                nonce=b"\\x9f\\x3a...",         # 12 random bytes
                key_version=1
              )
        """
        plaintext = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
        key_version = self.settings.active_encryption_key_version
        key = self._keys[key_version]
        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data=None)
        return EncryptedPayload(ciphertext=ciphertext, nonce=nonce, key_version=key_version)

    def decrypt_json(self, ciphertext: bytes, nonce: bytes, key_version: int) -> dict[str, Any]:
        """Decrypt an AES-256-GCM ciphertext and return the original dict.

        Looks up the key by the version recorded at encryption time, so rows encrypted with
        older key versions can still be read after a key rotation.
        AESGCM.decrypt raises InvalidTag if the ciphertext or nonce has been tampered with.

        Dry run:
            ciphertext=b"\\xab\\x12...", nonce=b"\\x9f\\x3a...", key_version=1
            → {"actors": [], "concluded_discussions": [], "open_action_items": []}
        """
        key = self._keys[key_version]
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, associated_data=None)
        return json.loads(plaintext.decode("utf-8"))

    def _load_keys(self) -> dict[int, bytes]:
        """Load and validate all encryption keys from settings at construction time.

        In local/test environments with no ENCRYPTION_KEYS_JSON set, falls back to a
        deterministic 32-zero-byte key so tests run without environment configuration.
        Outside local, the env var is mandatory to prevent accidental plaintext storage.

        Validation:
            - Each base64-encoded value must decode to exactly 32 bytes (256 bits for AES-256).
            - ACTIVE_ENCRYPTION_KEY_VERSION must be present in the loaded key map.

        Dry run (local, no env var):
            → {1: b"\\x00" * 32}
        Dry run (ENCRYPTION_KEYS_JSON='{"1":"<base64-32-bytes>","2":"<base64-32-bytes>"}',
                 ACTIVE_ENCRYPTION_KEY_VERSION=2):
            → {1: bytes(32), 2: bytes(32)}
        """
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

