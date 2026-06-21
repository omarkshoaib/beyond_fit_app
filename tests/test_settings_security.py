"""Security: refuse to run on the insecure default JWT secret in production."""
import pytest

from app.settings import Settings


def test_default_secret_rejected_in_production():
    s = Settings(app_env="production", auth_secret_key="change-me-in-production")
    with pytest.raises(ValueError, match="auth_secret_key"):
        s.require_secure_secret()


def test_short_secret_rejected_in_production():
    s = Settings(app_env="production", auth_secret_key="too-short")
    with pytest.raises(ValueError, match="auth_secret_key"):
        s.require_secure_secret()


def test_strong_secret_passes_in_production():
    s = Settings(app_env="production", auth_secret_key="a-real-32char-minimum-secret-value!!")
    s.require_secure_secret()  # must not raise


def test_default_secret_allowed_in_dev():
    s = Settings(app_env="dev", auth_secret_key="change-me-in-production")
    s.require_secure_secret()  # dev/test may use the default
