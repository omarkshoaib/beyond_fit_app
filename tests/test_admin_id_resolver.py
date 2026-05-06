from app.bot import _admin_chat_id


def test_admin_chat_id_prefers_admin_chat_id_env(monkeypatch):
    monkeypatch.setenv("ADMIN_CHAT_ID", "1111")
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "2222")
    assert _admin_chat_id() == 1111


def test_admin_chat_id_falls_back_to_legacy(monkeypatch):
    monkeypatch.delenv("ADMIN_CHAT_ID", raising=False)
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "3333")
    assert _admin_chat_id() == 3333


def test_admin_chat_id_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("ADMIN_CHAT_ID", raising=False)
    monkeypatch.delenv("ADMIN_TELEGRAM_ID", raising=False)
    assert _admin_chat_id() is None


def test_admin_chat_id_returns_none_when_non_integer(monkeypatch):
    monkeypatch.setenv("ADMIN_CHAT_ID", "not-a-number")
    monkeypatch.delenv("ADMIN_TELEGRAM_ID", raising=False)
    assert _admin_chat_id() is None
