"""Moomoo credential handling: all three documented private-key formats sign."""
import base64

import pytest

from tradingagents_worker.moomoo import MoomooClient, MoomooError

crypto = pytest.importorskip("cryptography")


def _client(key_text: str) -> MoomooClient:
    return MoomooClient("appkey-test", key_text)


def test_all_documented_key_formats_load_and_sign():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    fmts = {
        "pem": key.private_bytes(serialization.Encoding.PEM,
                                 serialization.PrivateFormat.PKCS8,
                                 serialization.NoEncryption()).decode(),
        "base64-der": base64.b64encode(key.private_bytes(
            serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())).decode(),
        "base64-seed": base64.b64encode(key.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption())).decode(),
    }
    for name, text in fmts.items():
        client = _client(text)
        sig = client._sign(1700000000000, "GET", "/quote/snapshot", "", b"")
        assert len(sig) == 88, name  # base64 of a 64-byte Ed25519 signature
        # Deterministic: same signing string → same signature.
        assert sig == client._sign(1700000000000, "GET", "/quote/snapshot", "", b"")


def test_rejects_non_ed25519_and_garbage():
    with pytest.raises(MoomooError):
        _client("not a key at all")._load_key()
    with pytest.raises(MoomooError):
        import base64 as b64
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        der64 = b64.b64encode(rsa_key.private_bytes(
            serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())).decode()
        _client(der64)._load_key()
