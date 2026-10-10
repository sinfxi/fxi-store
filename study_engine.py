"""Persistent study tracking and spaced repetition for DarsYar."""
from __future__ import annotations
from datetime import date, timedelta
import aiosqlite
from pathlib import Path
import os

DB_PATH = os.getenv("DB_PATH", "./data/studybot.db")

async def ensure_study_schema():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY, grade TEXT NOT NULL DEFAULT '',
            daily_goal INTEGER NOT NULL DEFAULT 30, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS study_days (
            user_id INTEGER NOT NULL, study_date TEXT NOT NULL,
            minutes INTEGER NOT NULL DEFAULT 0, sessions INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(user_id, study_date)
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS card_reviews (
            user_id INTEGER NOT NULL, card_id INTEGER NOT NULL, repetitions INTEGER NOT NULL DEFAULT 0,
            interval_days INTEGER NOT NULL DEFAULT 0, due_date TEXT NOT NULL,
            last_result TEXT NOT NULL DEFAULT 'again', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, card_id)
        )""")
        await db.commit()

async def mark_activity(user_id: int, minutes: int = 0):
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO user_profiles(user_id) VALUES(?)", (user_id,))
        await db.execute("""INSERT INTO study_days(user_id, study_date, minutes, sessions) VALUES(?,?,?,?)
            ON CONFLICT(user_id, study_date) DO UPDATE SET
            minutes=minutes+excluded.minutes, sessions=sessions+excluded.sessions""",
            (user_id, today, max(0, minutes), 1 if minutes > 0 else 0))
        await db.commit()

async def update_goal(user_id: int, minutes: int) -> int:
    minutes = max(5, min(int(minutes), 600))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO user_profiles(user_id) VALUES(?)", (user_id,))
        await db.execute("UPDATE user_profiles SET daily_goal=? WHERE user_id=?", (minutes, user_id))
        await db.commit()
    return minutes

async def update_profile(user_id: int, grade: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO user_profiles(user_id) VALUES(?)", (user_id,))
        if grade is not None:
            await db.execute("UPDATE user_profiles SET grade=? WHERE user_id=?", (grade[:40], user_id))
        async with db.execute("SELECT grade, daily_goal FROM user_profiles WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        await db.commit()
    return row or ("", 30)

async def save_card_review(user_id: int, card_id: int, result: str):
    today = date.today()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT repetitions FROM card_reviews WHERE user_id=? AND card_id=?", (user_id, card_id)) as cur:
            row = await cur.fetchone()
        reps = (row[0] if row else 0)
        if result == "known":
            reps += 1
            interval = [1, 3, 7, 14, 30, 60][min(reps - 1, 5)]
            due = today + timedelta(days=interval)
        else:
            reps = 0
            interval = 0
            due = today
        await db.execute("""INSERT INTO card_reviews(user_id, card_id, repetitions, interval_days, due_date, last_result, updated_at)
            VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, card_id) DO UPDATE SET repetitions=excluded.repetitions,
            interval_days=excluded.interval_days, due_date=excluded.due_date,
            last_result=excluded.last_result, updated_at=CURRENT_TIMESTAMP""",
            (user_id, card_id, reps, interval, due.isoformat(), result))
        await db.commit()
    await mark_activity(user_id)

async def due_card(user_id: int):
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT card_id FROM card_reviews WHERE user_id=? AND due_date<=? ORDER BY due_date, updated_at LIMIT 1", (user_id, today)) as cur:
            row = await cur.fetchone()
        async with db.execute("SELECT COUNT(*) FROM card_reviews WHERE user_id=? AND due_date<=?", (user_id, today)) as cur:
            count = (await cur.fetchone())[0]
    return (row[0] if row else None, count)

async def user_dashboard(user_id: int):
    today = date.today()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO user_profiles(user_id) VALUES(?)", (user_id,))
        async with db.execute("SELECT grade, daily_goal FROM user_profiles WHERE user_id=?", (user_id,)) as cur:
            grade, goal = await cur.fetchone()
        async with db.execute("SELECT COALESCE(SUM(minutes),0), COALESCE(SUM(sessions),0) FROM study_days WHERE user_id=? AND study_date=?", (user_id, today.isoformat())) as cur:
            minutes, sessions = await cur.fetchone()
        async with db.execute("SELECT study_date FROM study_days WHERE user_id=? AND sessions>0 ORDER BY study_date DESC", (user_id,)) as cur:
            dates = {date.fromisoformat(row[0]) async for row in cur}
        async with db.execute("SELECT COUNT(*) FROM card_reviews WHERE user_id=? AND due_date<=?", (user_id, today.isoformat())) as cur:
            due = (await cur.fetchone())[0]
        await db.commit()
    streak = 0
    day = today if today in dates else today - timedelta(days=1)
    while day in dates:
        streak += 1
        day -= timedelta(days=1)
    return {"grade": grade, "goal": goal, "minutes": minutes, "sessions": sessions, "streak": streak, "due": due}
