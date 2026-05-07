from app.config import Settings
from app.core.encryption import EncryptionService


def test_encrypt_decrypt_roundtrip() -> None:
    settings = Settings(
        encryption_keys_json={1: "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="},
        active_encryption_key_version=1,
    )
    service = EncryptionService(settings)
    payload = {"actors": [{"name": "Alex", "email": "alex@example.com"}]}

    encrypted = service.encrypt_json(payload)
    decrypted = service.decrypt_json(
        encrypted.ciphertext,
        encrypted.nonce,
        encrypted.key_version,
    )

    assert decrypted == payload
    assert encrypted.ciphertext != str(payload).encode()
    assert len(encrypted.nonce) == 12

