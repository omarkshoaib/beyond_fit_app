"""Security: access-token verifier must reject refresh/reset/verify tokens."""
from app.auth import jwt as J


def test_access_token_roundtrips():
    t = J.create_access_token("user-1")
    assert J.decode_token(t) == "user-1"


def test_refresh_token_rejected_as_access():
    t = J.create_refresh_token("user-1")
    assert J.decode_token(t) is None


def test_reset_token_rejected_as_access():
    t = J.create_reset_token("user-1")
    assert J.decode_token(t) is None


def test_verify_token_rejected_as_access():
    t = J.create_verify_token("user-1")
    assert J.decode_token(t) is None


def test_typed_decoders_still_work():
    assert J.decode_refresh_token(J.create_refresh_token("u")) == "u"
    assert J.decode_reset_token(J.create_reset_token("u")) == "u"
    assert J.decode_verify_token(J.create_verify_token("u")) == "u"
