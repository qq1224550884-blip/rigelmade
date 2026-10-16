"""限流回归：隔离数据库，不调用上游、不访问生产数据。"""
import importlib
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from test_wash import ASGIClient

import rate_limit


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(rate_limit, "_DATA_DIR", root))
        self.enterContext(patch.object(rate_limit, "_DB_PATH", root / "rate.sqlite3"))
        self.clock = self.enterContext(patch.object(rate_limit.time, "time", return_value=10000))

    def count(self):
        with closing(sqlite3.connect(rate_limit._DB_PATH, isolation_level=None)) as db:
            return db.execute("SELECT COUNT(*) FROM rate_events").fetchone()[0]

    def test_rejections_do_not_extend_window_and_wait_expires(self):
        for _ in range(2):
            self.assertEqual(rate_limit.check_rate_limit("test", "u", 2, 3600), 0)
        self.clock.return_value = 10030
        for _ in range(10):
            self.assertEqual(rate_limit.check_rate_limit("test", "u", 2, 3600), 3570)
        self.assertEqual(self.count(), 2)
        self.clock.return_value = 13600
        self.assertEqual(rate_limit.check_rate_limit("test", "u", 2, 3600), 0)

    def test_legacy_overcount_waits_until_enough_events_expire(self):
        rate_limit.check_rate_limit("test", "u", 2, 3600)
        with closing(sqlite3.connect(rate_limit._DB_PATH, isolation_level=None)) as db:
            db.executemany("INSERT INTO rate_events VALUES('test','u',?)", [(10010,), (10020,)])
        self.clock.return_value = 10100
        self.assertEqual(rate_limit.check_rate_limit("test", "u", 2, 3600), 3510)

    def test_short_window_does_not_prune_other_scopes(self):
        rate_limit.check_rate_limit("gen_user", "u", 2, 3600)
        self.clock.return_value = 11000
        rate_limit.check_rate_limit("login_ip", "ip", 2, 600)
        self.assertEqual(self.count(), 2)

    def test_ip_rejection_does_not_consume_user_slot(self):
        rate_limit.check_rate_limit("ip", "ip", 1, 3600)
        wait, events = rate_limit.check_rate_limits([("user", "u", 1, 3600), ("ip", "ip", 1, 3600)])
        self.assertEqual(wait, 3600)
        self.assertEqual(events, [])
        self.assertEqual(self.count(), 1)

    def test_failed_task_releases_only_its_slots(self):
        _, first = rate_limit.check_rate_limits([("user", "u", 2, 3600), ("ip", "ip", 2, 3600)])
        _, second = rate_limit.check_rate_limits([("user", "u", 2, 3600), ("ip", "ip", 2, 3600)])
        rate_limit.release_rate_limits(first)
        rate_limit.release_rate_limits(first)
        self.assertEqual(self.count(), len(second))

    def test_concurrent_requests_cannot_exceed_limit(self):
        rate_limit.check_rate_limit("init", "init", 1, 60)
        with ThreadPoolExecutor(max_workers=8) as pool:
            waits = list(pool.map(lambda _: rate_limit.check_rate_limit("user", "u", 5, 3600), range(20)))
        self.assertEqual(waits.count(0), 5)


class GenerationRateLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        cls.enterClassContext(patch.dict(os.environ, {
            "COMMERCIAL_DATA_DIR": str(root),
            "COMMERCIAL_DB_PATH": str(root / "commercial.sqlite3"),
            "COMMERCIAL_AUTH_SECRET": "isolated-generation-test-secret-1234567890",
            "AI_CANVAS_DATA_DIR": str(root / "render"),
            "WASH_API_ENABLED": "0",
        }))
        cls.gateway = importlib.import_module("commercial_app")

    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(self.gateway, "DB_PATH", root / "commercial.sqlite3"))
        self.enterContext(patch.object(rate_limit, "_DATA_DIR", root))
        self.enterContext(patch.object(rate_limit, "_DB_PATH", root / "rate.sqlite3"))
        self.enterContext(patch("requests.sessions.Session.request", side_effect=AssertionError("External API forbidden")))
        self.gateway.init_db()
        with self.gateway.transaction() as db:
            db.execute("INSERT INTO users VALUES('test-user','user@example.test','Test','unused','user','active',0)")
            db.execute("INSERT INTO model_prices VALUES('gpt-image-2.5','low',5,1,0)")
            db.execute("INSERT INTO credit_ledger VALUES('seed','test-user',1000,'test',NULL,'',0)")
        self.gateway.app.dependency_overrides[self.gateway.current_user] = lambda: {"id": "test-user"}
        self.addCleanup(self.gateway.app.dependency_overrides.clear)
        self.client = ASGIClient(self.gateway.app)

    def request(self, key):
        return self.client.post("/api/generate", json={
            "request": {"model": "gpt-image-2.5", "prompt": "test", "imageSize": "low"},
            "idempotencyKey": key,
        })

    def rate_count(self):
        if not rate_limit._DB_PATH.exists():
            return 0
        with closing(sqlite3.connect(rate_limit._DB_PATH, isolation_level=None)) as db:
            return db.execute("SELECT COUNT(*) FROM rate_events WHERE scope LIKE 'gen_%'").fetchone()[0]

    def test_failed_generation_refunds_credits_and_frequency(self):
        with patch.object(self.gateway.render_core, "generate", side_effect=HTTPException(502, "upstream failed")):
            for index in range(65):
                self.assertEqual(self.request(f"failed-{index}").status_code, 502)
        self.assertEqual(self.rate_count(), 0)
        with closing(self.gateway.db()) as db:
            self.assertEqual(self.gateway.user_balance(db, "test-user"), 1000)

    def test_idempotent_replay_and_invalid_request_do_not_count(self):
        with patch.object(self.gateway.render_core, "generate", return_value={"runId": "fixture"}) as generate:
            self.assertEqual(self.request("stable-key").status_code, 200)
            self.assertEqual(self.request("stable-key").status_code, 200)
            generate.assert_called_once()
        self.assertEqual(self.rate_count(), 2)
        self.assertEqual(self.request("").status_code, 400)
        self.assertEqual(self.rate_count(), 2)

    def test_insufficient_balance_does_not_count(self):
        with self.gateway.transaction() as db:
            db.execute("DELETE FROM credit_ledger")
        self.assertEqual(self.request("no-credit").status_code, 402)
        self.assertEqual(self.rate_count(), 0)

    def test_real_limit_returns_retry_after_without_charging(self):
        for _ in range(60):
            rate_limit.check_rate_limit("gen_user", "test-user", 60, 3600)
        response = self.request("blocked")
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers["Retry-After"]), 3500)
        self.assertEqual(self.rate_count(), 60)
        with closing(self.gateway.db()) as db:
            self.assertEqual(self.gateway.user_balance(db, "test-user"), 1000)


if __name__ == "__main__":
    unittest.main()
