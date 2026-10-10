import os
import tempfile
import unittest

import aiosqlite
from aiohttp.test_utils import TestClient, TestServer

import web_dashboard


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, user_id, text):
        self.sent.append((user_id, text))


class DashboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db_path = web_dashboard.DB_PATH
        self.old_token = os.environ.get("WEB_ADMIN_TOKEN")
        web_dashboard.DB_PATH = os.path.join(self.temp.name, "test.sqlite")
        os.environ["WEB_ADMIN_TOKEN"] = "unit-test-secret"
        async with aiosqlite.connect(web_dashboard.DB_PATH) as db:
            await db.executescript("""
                CREATE TABLE users(user_id INTEGER PRIMARY KEY, interactions INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE user_profiles(user_id INTEGER PRIMARY KEY, grade TEXT NOT NULL DEFAULT '', daily_goal INTEGER NOT NULL DEFAULT 30);
                CREATE TABLE study_days(user_id INTEGER NOT NULL, study_date TEXT NOT NULL, minutes INTEGER NOT NULL DEFAULT 0, sessions INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE learning_stats(user_id INTEGER PRIMARY KEY, quiz_answered INTEGER NOT NULL DEFAULT 0, quiz_correct INTEGER NOT NULL DEFAULT 0, cards_known INTEGER NOT NULL DEFAULT 0, cards_review INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE card_reviews(user_id INTEGER NOT NULL, card_id INTEGER NOT NULL, repetitions INTEGER NOT NULL DEFAULT 0, interval_days INTEGER NOT NULL DEFAULT 0, due_date TEXT NOT NULL, last_result TEXT NOT NULL DEFAULT 'again', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(user_id, card_id));
                INSERT INTO users(user_id, interactions) VALUES(12345, 7), (67890, 2);
                INSERT INTO user_profiles(user_id, grade, daily_goal) VALUES(12345, 'هشتم', 45);
                INSERT INTO study_days(user_id, study_date, minutes, sessions) VALUES(12345, date('now'), 25, 1);
                INSERT INTO learning_stats(user_id, quiz_answered, quiz_correct) VALUES(12345, 4, 3);
            """)
        self.bot = FakeBot()
        app = web_dashboard.create_web_app(self.bot, flashcards_count=84, subject_count=12)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        web_dashboard.DB_PATH = self.old_db_path
        if self.old_token is None:
            os.environ.pop("WEB_ADMIN_TOKEN", None)
        else:
            os.environ["WEB_ADMIN_TOKEN"] = self.old_token
        self.temp.cleanup()

    async def test_health_and_dashboard_are_public(self):
        health = await self.client.get("/health")
        self.assertEqual(health.status, 200)
        self.assertEqual((await health.json())["status"], "ok")
        page = await self.client.get("/")
        self.assertEqual(page.status, 200)
        self.assertIn("پنل مدیریت درس‌یار", await page.text())

    async def test_private_api_rejects_missing_token(self):
        response = await self.client.get("/api/summary")
        self.assertEqual(response.status, 401)

    async def test_summary_and_user_search(self):
        headers = {"Authorization": "Bearer unit-test-secret"}
        response = await self.client.get("/api/summary", headers=headers)
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(data["users"], 2)
        self.assertEqual(data["interactions"], 9)
        self.assertEqual(data["flashcards"], 84)
        self.assertEqual(data["subjects"], 12)
        users = await self.client.get("/api/users?search=هشتم", headers=headers)
        self.assertEqual(users.status, 200)
        listed = await users.json()
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["users"][0]["user_id"], 12345)
        self.assertEqual(listed["users"][0]["accuracy"], 75)

    async def test_broadcast_requires_confirmation_and_sends(self):
        headers = {"Authorization": "Bearer unit-test-secret", "Content-Type": "application/json"}
        denied = await self.client.post("/api/broadcast", headers=headers, json={"text": "اطلاعیه"})
        self.assertEqual(denied.status, 400)
        accepted = await self.client.post("/api/broadcast", headers=headers, json={"text": "اطلاعیه", "confirm": True})
        self.assertEqual(accepted.status, 200)
        result = await accepted.json()
        self.assertEqual(result["sent"], 2)
        self.assertEqual(len(self.bot.sent), 2)


if __name__ == "__main__":
    unittest.main()
