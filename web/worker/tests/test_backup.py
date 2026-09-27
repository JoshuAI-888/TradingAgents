"""Backup hygiene: snapshot everything EXCEPT secrets."""
from tradingagents_worker.backup import BUCKET, TABLES


def test_backup_excludes_secrets():
    assert "user_secrets" not in TABLES
    assert BUCKET == "backups"


def test_backup_covers_product_tables():
    for t in ("runs", "decisions", "run_digest", "price_bars", "news_items", "app_settings"):
        assert t in TABLES
