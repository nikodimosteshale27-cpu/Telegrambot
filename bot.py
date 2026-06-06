"""
Falah.bet Telegram Bot
- Button-driven admin panel (/admin)
- Modern ForceReply prompts for all inputs
- Railway-ready: auto-creates all DB tables on first deploy
- Required env: BOT_TOKEN, DATABASE_URL
- Optional env: ADMIN_USER_ID
"""
import asyncio
import csv
import io
import os
import random
from datetime import datetime, timedelta, timezone

import asyncpg
from dotenv import load_dotenv
from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()

BOT_TOKEN: str    = os.environ["BOT_TOKEN"]
DATABASE_URL: str = os.environ["DATABASE_URL"]
ADMIN_USER_ID: int = int(os.environ.get("ADMIN_USER_ID", "0"))

APP_URL         = "https://Falah.bet"
TOS_URL         = "https://www.notion.so/Terms-Responsible-Use-Policy-372c498a31788008a9bfc60271fb3ef3?source=copy_link"
REFERRAL_POINTS = 300
MAINTENANCE_MODE: bool = False

pool: asyncpg.Pool = None  # type: ignore

# ── Design system ──────────────────────────────────────────────────────────────

LEVEL_NAMES  = ["Starter", "Bronze", "Silver", "Gold", "Platinum", "Diamond", "Master", "Legend"]
LEVEL_BADGES = ["🪙", "🥉", "🥈", "🥇", "💎", "👑", "🔮", "🌟"]
RANK_MEDALS  = ["🥇", "🥈", "🥉"]

D    = "━━━━━━━━━━━━━━━━━━━━━━━━"
D2   = "─  ─  ─  ─  ─  ─  ─  ─"
LOGO = "🍀  <b>F A L A H . B E T</b>"


def progress_bar(current: int, total: int, length: int = 14) -> str:
    if total <= 0: return "▱" * length
    pct = min(current / total, 1.0)
    return "▰" * round(pct * length) + "▱" * (length - round(pct * length)) + f"  <code>{int(pct*100)}%</code>"


def level_info(pts: int, level: int):
    lo, hi = (level - 1) * 1000, level * 1000
    return max(0, pts - lo), max(0, hi - pts), hi - lo


def lv_badge(level: int) -> str: return LEVEL_BADGES[min(level - 1, len(LEVEL_BADGES) - 1)]
def lv_name(level: int) -> str:  return LEVEL_NAMES[min(level - 1, len(LEVEL_NAMES) - 1)]

# ── In-memory state: winners awaiting Fala account number ─────────────────────
# Maps user_id → {cid, rank, guess, question, admin_ids}
_fala_awaiting: dict[int, dict] = {}

def streak_label(streak: int) -> str:
    if streak >= 30: return f"🌋 <b>{streak}-day streak!</b>"
    if streak >= 14: return f"⚡ <b>{streak}-day streak</b>"
    if streak >= 7:  return f"🔥 <b>{streak}-day streak</b>"
    if streak >= 2:  return f"🔥 {streak}-day streak"
    return ""


# ── Messages ───────────────────────────────────────────────────────────────────

MSG = {
    "en": {
        "lang_button":   "🇬🇧  English",
        "age_text": (
            f"{LOGO}\n{D}\n\n"
            "🎲  <b>Welcome to Falah.bet!</b>\n\n"
            "⚠️  You must be <b>18+</b> to continue.\n"
            "Games involve real money — play responsibly.\n\n"
            f"{D}\nConfirm your age:"
        ),
        "age_continue": "✅  I'm 18+  —  Continue",
        "age_exit":     "❌  Exit",
        "tos_text": (
            f"{LOGO}\n{D}\n\n"
            "📋  <b>Terms &amp; Responsible Use</b>\n\n"
            "Please read our Terms before continuing.\n"
            "Tapping <b>Confirm</b> means you agree.\n\n"
            f"{D}"
        ),
        "tos_read":      "📄  Read Terms",
        "tos_continue":  "✅  Confirm",
        "tos_exit":      "❌  Exit",
        "exit_message":  "👋  You've exited. Type /start to return.",
        "maintenance":   f"{LOGO}\n{D}\n\n🔧  <b>Maintenance</b>\n\nBack shortly!\n\n{D}",
        "banned":        f"{LOGO}\n{D}\n\n🚫  <b>You are banned.</b>\n\nContact support if this is a mistake.\n\n{D}",
        "btn_tasks":     "📝  Tasks",
        "btn_rewards":   "🎁  Rewards",
        "btn_points":    "💰  Points",
        "btn_lb":        "🏆  Leaderboard",
        "btn_referral":  "🤝  Refer & Earn",
        "btn_ads":       "📺  Ads  (Soon)",
        "btn_settings":  "⚙️  Settings",
        "btn_open_app":  "🚀  Open App",
        "btn_back":      "🔙  Back",
        "btn_daily":     "🎁  Claim Daily Reward",
        "daily_already": "⏳  Already claimed today. Come back tomorrow!",
        "task_already":  "⚠️  Already completed.",
        "welcome_new":   f"{LOGO}\n{D}\n\n🎉  <b>You're in!</b>\n\nEarn points, win rewards, and climb the leaderboard! 🏆\n\n{D}",
        "ref_earned":    "🎉  <b>New Referral!</b>\n\nSomeone joined via your link!\n+<b>{pts} pts</b> 🏆",
        "level_up_msg":  "🎊  <b>Level Up!</b>\n\nYou're now {badge}  Level {level} — {name}!\nKeep going! 🚀",
        "contest_chose": "✅  <b>You chose {choice}!</b>\n\n🎉  Thank you for participating!",
        "contest_already": "✅  Already picked: {choice}",
        "contest_closed":  "⏰  This contest is closed.",
        "contest_deadline": "⏰  Deadline has passed.",
        "daily_ok":      "✅  +{pts} pts!\n🔥  {streak}-day streak  (+{bonus} bonus)",
        "daily_levelup": "\n🎊  LEVEL UP! → Level {level} {badge}",
    },
    "am": {
        "lang_button":   "🇪🇹  አማርኛ",
        "age_text": (
            f"{LOGO}\n{D}\n\n"
            "🎲  <b>እንኳን ወደ Falah.bet መጡ!</b>\n\n"
            "⚠️  ለመቀጠል ዕድሜዎ <b>18+</b> መሆን አለበት።\n"
            "ጨዋታዎቹ ገንዘብ ያካትታሉ — ኃላፊነት ይሰማዎ።\n\n"
            f"{D}\nዕድሜዎን ያረጋግጡ:"
        ),
        "age_continue": "✅  18+ ነኝ  —  ቀጥሉ",
        "age_exit":     "❌  ውጣ",
        "tos_text": (
            f"{LOGO}\n{D}\n\n"
            "📋  <b>የአጠቃቀም ውሎች</b>\n\n"
            "ከመቀጠልዎ በፊት ውሎቹን ያንብቡ።\n"
            "<b>አረጋግጣለሁ</b> ሲጫኑ ተስማምተዋሉ።\n\n"
            f"{D}"
        ),
        "tos_read":      "📄  ውሎቹን ያንብቡ",
        "tos_continue":  "✅  አረጋግጣለሁ",
        "tos_exit":      "❌  ውጣ",
        "exit_message":  "👋  ወጥተዋሉ። /start ይላኩ።",
        "maintenance":   f"{LOGO}\n{D}\n\n🔧  <b>ጥገና ላይ ነው</b>\n\nብዙም ሳይቆዩ ይመለሳሉ!\n\n{D}",
        "banned":        f"{LOGO}\n{D}\n\n🚫  <b>ተከልክለዋሉ።</b>\n\nስህተት ከሆነ ድጋፍን ያናግሩ።\n\n{D}",
        "btn_tasks":     "📝  ተግባራት",
        "btn_rewards":   "🎁  ሽልማቶች",
        "btn_points":    "💰  ነጥቦች",
        "btn_lb":        "🏆  ሰንጠረዥ",
        "btn_referral":  "🤝  ጓደኛ ጋብዝ",
        "btn_ads":       "📺  ማስታወቂያ (በቅርቡ)",
        "btn_settings":  "⚙️  ቅንብሮች",
        "btn_open_app":  "🚀  መተግበሪያ ክፈት",
        "btn_back":      "🔙  ተመለስ",
        "btn_daily":     "🎁  የዕለቱ ሽልማት",
        "daily_already": "⏳  ዛሬ ወስደዋሉ። ነገ ተመለሱ!",
        "task_already":  "⚠️  ቀደም ጨርሰዋሉ።",
        "welcome_new":   f"{LOGO}\n{D}\n\n🎉  <b>ገቡ!</b>\n\nነጥቦችን ያግኙ፣ ሽልማቶችን ያሸንፉ፣ ሰንጠረዡን ይቆጣጠሩ! 🏆\n\n{D}",
        "ref_earned":    "🎉  <b>አዲስ ጓደኛ!</b>\n\nአንድ ሰው በእርስዎ ሊንክ ተቀላቀለ!\n+<b>{pts} ነጥብ</b> 🏆",
        "level_up_msg":  "🎊  <b>ደረጃ ወጡ!</b>\n\nአሁን {badge}  ደረጃ {level} — {name}!\nቀጥሉ! 🚀",
        "contest_chose": "✅  <b>{choice} — መረጡ!</b>\n\n🎉  ስለተሳተፉ እናመሰግናለን!",
        "contest_already": "✅  ቀደም ምርጫዎ: {choice}",
        "contest_closed":  "⏰  ይህ ውድድር ተዘጋ።",
        "contest_deadline": "⏰  ጊዜ አልፏል።",
        "daily_ok":      "✅  +{pts} ነጥብ!\n🔥  {streak} ቀን ተከታታይ  (+{bonus} ቦነስ)",
        "daily_levelup": "\n🎊  ደረጃ ወጡ! → ደረጃ {level} {badge}",
    },
}

def lc(lang: str) -> dict: return MSG.get(lang, MSG["en"])
def lang_from(data: str) -> str: return "am" if ("_am_" in data or data.endswith("_am")) else "en"


# ══════════════════════════════════════════════════════════════════════════════
#  DB helpers
# ══════════════════════════════════════════════════════════════════════════════

async def get_setting(key: str, default: str = "") -> str:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM settings WHERE key=$1", key)
        return row["value"] if row else default

async def set_setting(key: str, value: str):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO settings(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=$2",
            key, value)

async def is_banned(uid: int) -> bool:
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT 1 FROM banned_users WHERE user_id=$1", uid) is not None

async def ban_user(uid: int, banned_by: int, reason: str = ""):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO banned_users(user_id,banned_by,reason) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
            uid, banned_by, reason)

async def unban_user(uid: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM banned_users WHERE user_id=$1", uid)

async def get_all_bans():
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM banned_users ORDER BY created_at DESC")

async def watch_user(admin_id: int, target_user_id: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO direct_chats(admin_id, target_user_id) VALUES($1,$2) ON CONFLICT DO NOTHING",
            admin_id, target_user_id)

async def unwatch_user(admin_id: int, target_user_id: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM direct_chats WHERE admin_id=$1 AND target_user_id=$2", admin_id, target_user_id)

async def get_watches_for_admin(admin_id: int):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM direct_chats WHERE admin_id=$1 ORDER BY created_at DESC", admin_id)

async def get_watching_admins(target_user_id: int):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT admin_id FROM direct_chats WHERE target_user_id=$1", target_user_id)

# ── Guess Game DB helpers ────────────────────────────────────────────────────

async def create_contest(admin_id: int, question: str, contest_type: str, deadline_hours: float,
                         team1: str = "", team2: str = ""):
    deadline = datetime.now(timezone.utc) + timedelta(hours=deadline_hours)
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "INSERT INTO guess_contests(admin_id,question,contest_type,deadline,team1,team2) "
            "VALUES($1,$2,$3,$4,$5,$6) RETURNING *",
            admin_id, question, contest_type, deadline, team1, team2)

async def get_contest(contest_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM guess_contests WHERE id=$1", contest_id)

async def get_open_contests():
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM guess_contests WHERE status='open' ORDER BY created_at DESC")

async def submit_guess(contest_id: int, user_id: int, guess: str):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO guess_entries(contest_id,user_id,guess) VALUES($1,$2,$3) "
            "ON CONFLICT(contest_id,user_id) DO NOTHING",
            contest_id, user_id, guess)

async def get_user_guess(contest_id: int, user_id: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM guess_entries WHERE contest_id=$1 AND user_id=$2",
            contest_id, user_id)

async def resolve_contest(contest_id: int, correct_answer: str):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE guess_contests SET status='resolved', correct_answer=$1 WHERE id=$2",
            correct_answer.strip(), contest_id)
        await conn.execute(
            "UPDATE guess_entries SET is_correct=TRUE "
            "WHERE contest_id=$1 AND lower(trim(guess))=lower(trim($2))",
            contest_id, correct_answer.strip())

async def get_correct_guessers(contest_id: int, limit: int = 10):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT ge.*, u.username FROM guess_entries ge "
            "LEFT JOIN users u ON u.id=ge.user_id "
            "WHERE ge.contest_id=$1 AND ge.is_correct=TRUE "
            "ORDER BY ge.submitted_at ASC LIMIT $2",
            contest_id, limit)

async def purge_losers(contest_id: int, keep_top: int = 10):
    """Delete all incorrect entries; keep only the fastest `keep_top` correct ones."""
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM guess_entries WHERE contest_id=$1 AND is_correct=FALSE",
            contest_id)
        await conn.execute("""
            DELETE FROM guess_entries
            WHERE contest_id=$1 AND is_correct=TRUE
              AND user_id NOT IN (
                SELECT user_id FROM guess_entries
                WHERE contest_id=$1 AND is_correct=TRUE
                ORDER BY submitted_at ASC LIMIT $2)
        """, contest_id, keep_top)

async def get_contest_entry_count(contest_id: int) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM guess_entries WHERE contest_id=$1", contest_id)
        return row["n"] if row else 0

async def get_all_users():
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT id FROM users")

# ── End Guess Game DB helpers ────────────────────────────────────────────────

async def get_or_create_user(uid, username, lang="en", referred_by=None):
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT id FROM users WHERE id=$1", uid)
        got_ref = False
        if not existing:
            await conn.execute(
                "INSERT INTO users(id,username,lang,referred_by) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                uid, username, lang, referred_by)
            if referred_by and referred_by != uid:
                ref = await conn.fetchrow("SELECT id FROM users WHERE id=$1", referred_by)
                if ref:
                    await conn.execute(
                        "UPDATE users SET points=points+$1, referral_count=referral_count+1 WHERE id=$2",
                        REFERRAL_POINTS, referred_by)
                    got_ref = True
        return await conn.fetchrow("SELECT * FROM users WHERE id=$1", uid), got_ref

async def get_user(uid: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE id=$1", uid)

async def get_user_by_username(username: str):
    clean = username.lstrip("@").lower()
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE lower(username)=$1", clean)

async def set_user_lang(uid: int, lang: str):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET lang=$1 WHERE id=$2", lang, uid)

async def add_points(uid: int, pts: int) -> tuple[bool, int]:
    async with pool.acquire() as conn:
        old = await conn.fetchrow("SELECT points,level FROM users WHERE id=$1", uid)
        await conn.execute("UPDATE users SET points=GREATEST(0,points+$1) WHERE id=$2", pts, uid)
        user = await conn.fetchrow("SELECT points,level FROM users WHERE id=$1", uid)
        if user:
            new_level = user["points"] // 1000 + 1
            if new_level != user["level"]:
                await conn.execute("UPDATE users SET level=$1 WHERE id=$2", new_level, uid)
                return True, new_level
        return False, (old["level"] if old else 1)

async def set_points(uid: int, pts: int):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET points=$1 WHERE id=$2", max(0, pts), uid)
        new_level = max(0, pts) // 1000 + 1
        await conn.execute("UPDATE users SET level=$1 WHERE id=$2", new_level, uid)

async def claim_daily(uid: int) -> dict:
    user = await get_user(uid)
    if not user:
        return {"ok": False, "pts": 0, "streak": 0}
    now = datetime.now(timezone.utc)
    streak = user.get("streak", 0) or 0
    if user["daily_claimed_at"]:
        last = user["daily_claimed_at"]
        if last.tzinfo is None: last = last.replace(tzinfo=timezone.utc)
        hrs = (now - last).total_seconds() / 3600
        if hrs < 24: return {"ok": False, "pts": 0, "streak": streak}
        streak = streak + 1 if hrs <= 48 else 1
    else:
        streak = 1
    bonus = min(streak * 10, 200)
    pts = 50 + user["level"] * 10 + bonus
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET daily_claimed_at=$1, streak=$2 WHERE id=$3", now, streak, uid)
    leveled_up, new_level = await add_points(uid, pts)
    return {"ok": True, "pts": pts, "streak": streak, "streak_bonus": bonus, "leveled_up": leveled_up, "new_level": new_level}

async def get_leaderboard(limit: int):
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM users ORDER BY points DESC LIMIT $1", limit)

async def get_user_rank(uid: int) -> int:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM users ORDER BY points DESC")
        for i, r in enumerate(rows):
            if r["id"] == uid: return i + 1
        return 0

async def is_admin(uid: int) -> bool:
    if uid == ADMIN_USER_ID: return True
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT 1 FROM admins WHERE user_id=$1", uid) is not None

async def get_admin_record(uid: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM admins WHERE user_id=$1", uid)

async def add_admin(uid: int, created_by: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins(user_id,role,created_by) VALUES($1,'admin',$2) ON CONFLICT DO NOTHING",
            uid, created_by)

async def remove_admin(uid: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM admins WHERE user_id=$1", uid)

async def get_all_admins():
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM admins ORDER BY created_at")

async def get_all_users():
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT id FROM users")

async def get_all_users_full():
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM users ORDER BY points DESC")

async def get_active_tasks():
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM tasks WHERE active=true ORDER BY id")

async def get_all_tasks():
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM tasks ORDER BY id")

async def get_task_by_id(tid: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM tasks WHERE id=$1", tid)

async def create_task(title, description, points, link=None):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "INSERT INTO tasks(title,description,points,link) VALUES($1,$2,$3,$4) RETURNING *",
            title, description, points, link)

async def update_task(tid, title, link, points, description=""):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tasks SET title=$1,link=$2,points=$3,description=$4 WHERE id=$5",
            title, link, points, description, tid)

async def delete_task(tid: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM task_completions WHERE task_id=$1", tid)
        await conn.execute("DELETE FROM tasks WHERE id=$1", tid)

async def toggle_task(tid: int, active: bool):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE tasks SET active=$1 WHERE id=$2", active, tid)

async def get_task_completion_count(tid: int) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) as c FROM task_completions WHERE task_id=$1", tid)
        return row["c"] if row else 0

async def has_completed_task(uid: int, tid: int) -> bool:
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT 1 FROM task_completions WHERE user_id=$1 AND task_id=$2", uid, tid) is not None

async def complete_task(uid, tid, pts):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO task_completions(user_id,task_id) VALUES($1,$2)", uid, tid)
    return await add_points(uid, pts)

async def get_user_completed_task_ids(uid: int) -> list[int]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT task_id FROM task_completions WHERE user_id=$1", uid)
        return [r["task_id"] for r in rows]

async def get_active_rewards():
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM rewards WHERE active=true ORDER BY id")

async def get_all_rewards():
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM rewards ORDER BY id")

async def create_reward(title, description, cost):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "INSERT INTO rewards(title,description,cost) VALUES($1,$2,$3) RETURNING *",
            title, description, cost)

async def delete_reward(rid: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM rewards WHERE id=$1", rid)

async def toggle_reward(rid: int, active: bool):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE rewards SET active=$1 WHERE id=$2", active, rid)

async def log_draw(winner_id, prize_pts, run_by, notes=""):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO draw_history(winner_id,prize_pts,run_by,notes) VALUES($1,$2,$3,$4)",
            winner_id, prize_pts, run_by, notes)

async def get_draw_history(limit=10):
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT dh.*,u.username FROM draw_history dh LEFT JOIN users u ON u.id=dh.winner_id ORDER BY dh.created_at DESC LIMIT $1",
            limit)

async def seed_tasks():
    if await get_active_tasks(): return
    await create_task("Join our Official Channel", "Subscribe to stay updated",    200, "https://t.me/falahbetofficial")
    await create_task("Open the App",              "Launch Falah.bet and explore", 150, None)


# ══════════════════════════════════════════════════════════════════════════════
#  Guards & helpers
# ══════════════════════════════════════════════════════════════════════════════

async def guard(update: Update, lang: str = "en") -> bool:
    uid = update.effective_user.id if update.effective_user else None
    if uid is None: return False
    if await is_admin(uid): return True
    if await is_banned(uid):
        text = lc(lang)["banned"]
        if update.message: await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        elif update.callback_query: await update.callback_query.answer("🚫 You are banned.", show_alert=True)
        return False
    if MAINTENANCE_MODE:
        text = lc(lang)["maintenance"]
        if update.message: await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        elif update.callback_query: await update.callback_query.answer("🔧 Maintenance mode.", show_alert=True)
        return False
    return True

async def level_up_notify(bot, uid: int, new_level: int):
    try:
        user = await get_user(uid)
        lang = user["lang"] if user else "en"
        t = lc(lang)
        text = t["level_up_msg"].format(
            badge=lv_badge(new_level), level=new_level, name=lv_name(new_level))
        await bot.send_message(uid, text, parse_mode=ParseMode.HTML)
    except Exception: pass

async def resolve_target(arg: str):
    if arg.startswith("@") or not arg.lstrip("-").isdigit():
        user = await get_user_by_username(arg)
        if not user: return None
        label = f"@{user['username']}" if user["username"] else f"<code>{user['id']}</code>"
        return user["id"], label
    uid = int(arg)
    user = await get_user(uid)
    label = f"@{user['username']}" if (user and user["username"]) else f"<code>{uid}</code>"
    return uid, label

async def build_profile_card(uid: int, bot, lang: str = "en", show_menu=True):
    user = await get_user(uid)
    if not user: return "", None
    rank = await get_user_rank(uid)
    uname = f"@{user['username']}" if user["username"] else f"User {user['id']}"
    pts, level = user["points"], user["level"]
    streak = user.get("streak", 0) or 0
    refs   = user.get("referral_count", 0) or 0
    within, to_next, span = level_info(pts, level)
    bar  = progress_bar(within, span)
    sl   = streak_label(streak)
    card = (
        f"{LOGO}\n{D}\n\n"
        f"👤  <b>{uname}</b>  •  {lv_badge(level)}  <b>Lv.{level}</b>  •  🏆  #{rank}\n"
        f"{D2}\n"
        f"💰  <b>{pts:,} pts</b>\n{bar}\n"
        f"<i>+{to_next:,} to Lv.{level+1}</i>\n"
        f"{D2}\n"
        f"🤝  Refs: <b>{refs}</b>"
        + (f"   •   {sl}" if sl else "")
        + f"\n{D}"
    )
    photo = None
    try:
        bot_info = await bot.get_me()
        chat = await bot.get_chat(bot_info.id)
        if chat.photo:
            file = await bot.get_file(chat.photo.big_file_id)
            photo = await file.download_as_bytearray()
    except Exception:
        pass
    return card, photo

def menu_keyboard(lang: str, for_admin: bool = False) -> InlineKeyboardMarkup:
    t = lc(lang)
    rows = [
        [InlineKeyboardButton(t["btn_tasks"],   callback_data=f"menu_tasks_{lang}"),
         InlineKeyboardButton(t["btn_lb"],      callback_data=f"menu_lb_{lang}")],
        [InlineKeyboardButton(t["btn_referral"],callback_data=f"menu_referral_{lang}"),
         InlineKeyboardButton(t["btn_settings"],callback_data=f"menu_settings_{lang}")],
        [InlineKeyboardButton(t["btn_open_app"],web_app=WebAppInfo(url=APP_URL))],
    ]
    if for_admin:
        rows.append([InlineKeyboardButton("🛡️  Admin Panel", callback_data="ap_main")])
    return InlineKeyboardMarkup(rows)

def back_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(lc(lang)["btn_back"], callback_data=f"menu_back_{lang}")]])

async def _edit(q, text: str, kb, parse_mode=ParseMode.HTML):
    try:
        if q.message.caption is not None:
            await q.edit_message_caption(caption=text, parse_mode=parse_mode, reply_markup=kb)
        else:
            await q.edit_message_text(text=text, parse_mode=parse_mode, reply_markup=kb)
    except Exception: pass

async def send_main_menu(chat_id: int, lang: str, bot, old_message=None):
    if old_message:
        try: await old_message.delete()
        except Exception: pass
    await bot.send_chat_action(chat_id, ChatAction.TYPING)
    card, photo = await build_profile_card(chat_id, bot, lang=lang, show_menu=True)
    kb = menu_keyboard(lang, for_admin=await is_admin(chat_id))
    if photo:
        await bot.send_photo(chat_id=chat_id, photo=bytes(photo), caption=card,
                             parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await bot.send_message(chat_id=chat_id, text=card, parse_mode=ParseMode.HTML, reply_markup=kb)


# ══════════════════════════════════════════════════════════════════════════════
#  User onboarding & menu
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = ctx.args or []
    referred_by = None
    for arg in args:
        if arg.startswith("ref_"):
            try: referred_by = int(arg[4:])
            except ValueError: pass

    user = await get_user(uid)
    if user:
        if not await guard(update, user["lang"] or "en"): return
        await send_main_menu(uid, user["lang"] or "en", ctx.bot, update.message)
        return
    if not await guard(update): return
    if referred_by: ctx.user_data["referred_by"] = referred_by
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(MSG["en"]["lang_button"], callback_data="lang_en"),
        InlineKeyboardButton(MSG["am"]["lang_button"], callback_data="lang_am"),
    ]])
    await update.message.reply_text(
        f"{LOGO}\n{D}\n\n🌐  <b>Welcome!</b>  Please choose your language:",
        parse_mode=ParseMode.HTML, reply_markup=kb)

async def cb_lang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not await guard(update): return
    lang = q.data.split("_")[1]
    t = lc(lang)
    await q.delete_message()
    await ctx.bot.send_chat_action(q.from_user.id, ChatAction.TYPING)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(t["age_continue"], callback_data=f"age_yes_{lang}"),
        InlineKeyboardButton(t["age_exit"],     callback_data=f"age_no_{lang}"),
    ]])
    await ctx.bot.send_message(q.from_user.id, t["age_text"], parse_mode=ParseMode.HTML, reply_markup=kb)

async def cb_age_yes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = lang_from(q.data)
    t = lc(lang)
    await q.delete_message()
    await ctx.bot.send_chat_action(q.from_user.id, ChatAction.TYPING)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t["tos_read"],     url=TOS_URL)],
        [InlineKeyboardButton(t["tos_continue"], callback_data=f"tos_yes_{lang}"),
         InlineKeyboardButton(t["tos_exit"],     callback_data=f"tos_no_{lang}")],
    ])
    await ctx.bot.send_message(q.from_user.id, t["tos_text"], parse_mode=ParseMode.HTML, reply_markup=kb)

async def cb_age_no(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = lang_from(q.data)
    await q.delete_message()
    await ctx.bot.send_message(q.from_user.id, lc(lang)["exit_message"], parse_mode=ParseMode.HTML)

async def cb_tos_yes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = lang_from(q.data)
    uid  = q.from_user.id
    referred_by = ctx.user_data.pop("referred_by", None)
    _, got_ref = await get_or_create_user(uid, q.from_user.username, lang, referred_by)
    await q.delete_message()
    if got_ref and referred_by:
        try:
            ref_user = await get_user(referred_by)
            ref_lang = ref_user["lang"] if ref_user else "en"
            ref_msg = lc(ref_lang)["ref_earned"].format(pts=REFERRAL_POINTS)
            await ctx.bot.send_message(referred_by, ref_msg, parse_mode=ParseMode.HTML)
        except Exception: pass
    await ctx.bot.send_chat_action(uid, ChatAction.TYPING)
    await ctx.bot.send_message(uid, lc(lang)["welcome_new"], parse_mode=ParseMode.HTML)
    await asyncio.sleep(0.5)
    await send_main_menu(uid, lang, ctx.bot)

async def cb_tos_no(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = lang_from(q.data)
    await q.delete_message()
    await ctx.bot.send_message(q.from_user.id, lc(lang)["exit_message"], parse_mode=ParseMode.HTML)

async def cb_menu_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = lang_from(q.data)
    if not await guard(update, lang): return
    await send_main_menu(q.from_user.id, lang, ctx.bot, q.message)

async def cb_menu_points(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = lang_from(q.data)
    if not await guard(update, lang): return
    t = lc(lang)
    user = await get_user(q.from_user.id)
    if not user: return
    pts, level = user["points"], user["level"]
    streak = user.get("streak", 0) or 0
    within, to_next, span = level_info(pts, level)
    bar = progress_bar(within, span)
    text = (
        f"{LOGO}\n{D}\n\n💰  <b>Your Points</b>\n\n"
        f"{lv_badge(level)}  <b>Level {level}</b>  —  <i>{lv_name(level)}</i>\n\n"
        f"💰  Balance: <b>{pts:,} pts</b>\n\n"
        f"<b>Progress to Level {level+1}</b>\n{bar}\n"
        f"<i>{within:,} / {span:,}  ({to_next:,} remaining)</i>\n\n"
        f"{D2}\n🔥  Streak: <b>{streak} days</b>  (+{min(streak*10,200)} bonus/day)\n\n{D}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t["btn_daily"], callback_data=f"daily_{lang}")],
        [InlineKeyboardButton(t["btn_back"],  callback_data=f"menu_back_{lang}")],
    ])
    await _edit(q, text, kb)

async def cb_daily(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    lang = lang_from(q.data)
    if not await guard(update, lang): return
    result = await claim_daily(q.from_user.id)
    t = lc(lang)
    if result["ok"]:
        alert = t["daily_ok"].format(
            pts=result["pts"], streak=result["streak"], bonus=result["streak_bonus"])
        if result.get("leveled_up"):
            alert += t["daily_levelup"].format(
                level=result["new_level"], badge=lv_badge(result["new_level"]))
            await level_up_notify(ctx.bot, q.from_user.id, result["new_level"])
        await q.answer(alert, show_alert=True)
    else:
        await q.answer(t["daily_already"], show_alert=True)

async def cb_menu_rewards(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = lang_from(q.data)
    if not await guard(update, lang): return
    rewards = await get_active_rewards()
    if not rewards:
        text = f"{LOGO}\n{D}\n\n🎁  <b>Rewards</b>\n\n📭  No rewards available right now.\n\n{D}"
    else:
        lines = [f"🎁  <b>{r['title']}</b>  —  {r['cost']:,} pts"
                 + (f"\n    <i>{r['description']}</i>" if r["description"] else "")
                 for r in rewards]
        text = f"{LOGO}\n{D}\n\n🎁  <b>Rewards</b>\n\n" + "\n\n".join(lines) + f"\n\n{D}"
    await _edit(q, text, back_kb(lang))

async def cb_menu_lb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = lang_from(q.data)
    if not await guard(update, lang): return
    uid = q.from_user.id
    top  = await get_leaderboard(10)
    rank = await get_user_rank(uid)
    user = await get_user(uid)
    lines = []
    for i, u in enumerate(top):
        medal = RANK_MEDALS[i] if i < 3 else f"#{i+1}"
        uname = f"@{u['username']}" if u["username"] else f"User {u['id']}"
        you   = "  ← <i>You</i>" if u["id"] == uid else ""
        lines.append(f"{medal}  {lv_badge(u['level'])}  <b>{uname}</b>  —  {u['points']:,} pts{you}")
    your_rank = ""
    if user and rank > 10:
        your_rank = f"\n{D2}\n📊  Your position: <b>#{rank}</b>  —  {user['points']:,} pts"
    await _edit(q, f"{LOGO}\n{D}\n\n🏆  <b>Leaderboard</b>\n\n" + "\n".join(lines) + your_rank + f"\n\n{D}", back_kb(lang))

async def cb_menu_ads(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("📺  Ads feature coming soon!", show_alert=True)

async def cb_menu_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = lang_from(q.data)
    if not await guard(update, lang): return
    t = lc(lang)
    text = f"{LOGO}\n{D}\n\n⚙️  <b>Settings</b>\n\n🌐  Choose your language:\n\n{D}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇬🇧  English",  callback_data="switch_lang_en"),
         InlineKeyboardButton("🇪🇹  አማርኛ",   callback_data="switch_lang_am")],
        [InlineKeyboardButton(t["btn_back"],    callback_data=f"menu_back_{lang}")],
    ])
    await _edit(q, text, kb)

async def cb_switch_lang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    new_lang = q.data.split("_")[2]
    if not await guard(update, new_lang): return
    await set_user_lang(q.from_user.id, new_lang)
    await q.answer("✅  Language updated!")
    await send_main_menu(q.from_user.id, new_lang, ctx.bot, q.message)

async def cb_menu_referral(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = lang_from(q.data)
    if not await guard(update, lang): return
    uid  = q.from_user.id
    user = await get_user(uid)
    if not user: return
    bot_info = await ctx.bot.get_me()
    link  = f"https://t.me/{bot_info.username}?start=ref_{uid}"
    refs  = user.get("referral_count", 0) or 0
    earned = refs * REFERRAL_POINTS
    bar   = progress_bar(refs, max(refs + 5, 10))
    text  = (
        f"{LOGO}\n{D}\n\n🤝  <b>Refer &amp; Earn</b>\n\n"
        f"Invite friends and earn  <b>{REFERRAL_POINTS} pts</b>  each!\n\n"
        f"{D2}\n"
        f"👥  Friends referred: <b>{refs}</b>\n{bar}\n"
        f"💰  Earned: <b>{earned:,} pts</b>\n\n"
        f"🔗  <b>Your link:</b>\n<code>{link}</code>\n\n{D}"
    )
    share = "Join+Falah.bet+and+earn+points+with+me%21"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤  Share Your Link", url=f"https://t.me/share/url?url={link}&text={share}")],
        [InlineKeyboardButton(lc(lang)["btn_back"],  callback_data=f"menu_back_{lang}")],
    ])
    await _edit(q, text, kb)

# Tasks
async def show_task_card(q, lang: str, index: int):
    uid  = q.from_user.id
    tasks = await get_active_tasks()
    done_ids = await get_user_completed_task_ids(uid)
    if not tasks:
        await _edit(q, f"{LOGO}\n{D}\n\n📭  <b>No tasks available right now.</b>\n\n{D}", back_kb(lang))
        return
    index = max(0, min(index, len(tasks) - 1))
    task  = tasks[index]
    done  = task["id"] in done_ids
    total = len(tasks)
    done_count = sum(1 for tid in done_ids if any(t["id"] == tid for t in tasks))
    overall = progress_bar(done_count, total, 10)
    pts = task["points"]
    diff = "⭐⭐⭐  <i>High Reward</i>" if pts >= 500 else ("⭐⭐  <i>Medium Reward</i>" if pts >= 200 else "⭐  <i>Quick Reward</i>")
    text = (
        f"{LOGO}\n{D}\n\n"
        f"📋  <b>Task {index+1} of {total}</b>   <i>{done_count}/{total} done</i>  {overall}\n\n"
        f"<b>{task['title']}</b>\n"
        + (f"<i>{task['description']}</i>\n\n" if task["description"] else "\n")
        + f"{diff}\n💰  Reward: <b>+{pts:,} pts</b>\n\n{D2}\n"
        + ("✅  <b>Completed!</b>" if done else "⏳  <b>Not yet completed</b>")
        + f"\n\n{D}"
    )
    rows = []
    if done:
        rows.append([InlineKeyboardButton("✅  Already Completed", callback_data=f"task_already_{lang}")])
    elif task["link"]:
        yt = "youtube.com" in task["link"] or "youtu.be" in task["link"]
        rows.append([InlineKeyboardButton("▶️  Subscribe on YouTube" if yt else "📢  Join Channel / Group", url=task["link"])])
        rows.append([InlineKeyboardButton(f"✅  Verify &amp; Claim  (+{pts:,} pts)", callback_data=f"task_claim_{task['id']}_{lang}")])
    else:
        rows.append([InlineKeyboardButton(f"🚀  Open App  (+{pts:,} pts)", web_app=WebAppInfo(url=APP_URL))])
        rows.append([InlineKeyboardButton("✅  Mark as Done", callback_data=f"task_claim_{task['id']}_{lang}")])
    if total > 1:
        prev_i = (index - 1 + total) % total
        next_i = (index + 1) % total
        rows.append([
            InlineKeyboardButton("◀️", callback_data=f"tasks_page_{prev_i}_{lang}"),
            InlineKeyboardButton(f"  {index+1} / {total}  ", callback_data=f"task_noop_{lang}"),
            InlineKeyboardButton("▶️", callback_data=f"tasks_page_{next_i}_{lang}"),
        ])
    rows.append([InlineKeyboardButton(lc(lang)["btn_back"], callback_data=f"menu_back_{lang}")])
    await _edit(q, text, InlineKeyboardMarkup(rows))

async def cb_menu_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = lang_from(q.data)
    if not await guard(update, lang): return
    await show_task_card(q, lang, 0)

async def cb_tasks_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    parts = q.data.split("_")
    await show_task_card(q, parts[3], int(parts[2]))

async def cb_task_noop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

async def cb_task_already(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer(lc(lang_from(q.data))["task_already"], show_alert=True)

async def cb_task_claim(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.split("_")
    task_id, lang = int(parts[2]), parts[3]
    uid = q.from_user.id
    if not await guard(update, lang): return
    tasks = await get_active_tasks()
    task  = next((t for t in tasks if t["id"] == task_id), None)
    if not task: await q.answer(); return
    if await has_completed_task(uid, task_id):
        await q.answer(lc(lang)["task_already"], show_alert=True); return
    leveled_up, new_level = await complete_task(uid, task_id, task["points"])
    alert = f"🎉  +{task['points']:,} pts!\n\"{task['title']}\" complete!"
    if leveled_up:
        alert += f"\n\n🏆  LEVEL UP! → Level {new_level} {lv_badge(new_level)}"
        await level_up_notify(ctx.bot, uid, new_level)
    await q.answer(alert, show_alert=True)
    current_index = next((i for i, t in enumerate(tasks) if t["id"] == task_id), 0)
    await show_task_card(q, lang, (current_index + 1) % len(tasks))


# ══════════════════════════════════════════════════════════════════════════════
#  ████████████████   A D M I N   P A N E L   ████████████████
# ══════════════════════════════════════════════════════════════════════════════

# ── Prompt helper ──────────────────────────────────────────────────────────────

async def admin_prompt(bot, chat_id: int, title: str, body: str, example: str = "", action: str = ""):
    """Send a beautiful ForceReply prompt and set the pending action."""
    lines = [
        f"{LOGO}\n{D}\n\n"
        f"✏️  <b>{title}</b>\n\n"
        f"{body}"
    ]
    if example:
        lines.append(f"\n\n{D2}\n📌  <b>Example:</b>  <code>{example}</code>")
    lines.append(f"\n\n{D}\n<i>Reply to this message with your input.</i>")
    return await bot.send_message(
        chat_id, "".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=ForceReply(selective=True, input_field_placeholder=example or "Type here…"),
    )

async def admin_result(bot, chat_id: int, icon: str, title: str, body: str, extra: str = ""):
    """Send a styled result card after an admin action."""
    await bot.send_message(
        chat_id,
        f"{D}\n{icon}  <b>{title}</b>\n{D2}\n{body}"
        + (f"\n{D2}\n{extra}" if extra else "")
        + f"\n{D}",
        parse_mode=ParseMode.HTML,
    )

def _ap(action: str) -> str:
    """Shorthand callback prefix for admin panel."""
    return f"ap_{action}"


# ── Main admin panel ───────────────────────────────────────────────────────────

def ap_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥  Users",       callback_data="ap_users"),
         InlineKeyboardButton("👑  Admins",      callback_data="ap_admins")],
        [InlineKeyboardButton("📋  Tasks",       callback_data="ap_tasks"),
         InlineKeyboardButton("📊  Statistics",  callback_data="ap_stats")],
        [InlineKeyboardButton("📣  Broadcast",   callback_data="ap_broadcast"),
         InlineKeyboardButton("⚙️  System",      callback_data="ap_system")],
        [InlineKeyboardButton("💬  Direct Chat", callback_data="ap_directchat"),
         InlineKeyboardButton("🎯  Guess Game",  callback_data="ap_guessgame")],
    ])

def ap_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Admin Panel", callback_data="ap_main")]])

async def show_ap_main(q_or_chat, bot=None, user_id: int = None):
    """Show the main admin panel. Works with callback query or direct message."""
    uid = q_or_chat.from_user.id if hasattr(q_or_chat, "from_user") else user_id
    admins = await get_all_admins()
    users  = await get_all_users()
    bans   = await get_all_bans()
    tasks  = await get_all_tasks()
    maint  = "🔴  ON" if MAINTENANCE_MODE else "🟢  OFF"
    text = (
        f"{LOGO}\n{D}\n\n"
        f"🛡️  <b>Admin Control Panel</b>\n\n"
        f"{D2}\n"
        f"👥  Users:  <b>{len(users):,}</b>   🚫  Banned: <b>{len(bans)}</b>\n"
        f"📋  Tasks:  <b>{sum(1 for t in tasks if t['active'])} active</b> / {len(tasks)} total\n"
        f"👑  Sub-admins: <b>{len(admins)}</b>\n"
        f"🔧  Maintenance: {maint}\n"
        f"{D2}\n"
        f"<i>Select a category below:</i>\n{D}"
    )
    if hasattr(q_or_chat, "message"):
        try:
            if q_or_chat.message.caption is not None:
                await q_or_chat.edit_message_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=ap_main_kb())
            else:
                await q_or_chat.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=ap_main_kb())
        except Exception:
            await q_or_chat.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=ap_main_kb())
    else:
        await q_or_chat.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=ap_main_kb())


async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_admin(uid):
        await update.message.reply_text(
            f"{LOGO}\n{D}\n\n🚫  <b>Access Denied</b>\n\nThis panel is for admins only.\n\n{D}",
            parse_mode=ParseMode.HTML)
        return
    await show_ap_main(update.message)

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_admin(uid):
        return                          # silently ignore for non-admins
    user = await get_user(uid)
    lang = user["lang"] if user else "en"
    await send_main_menu(uid, lang, ctx.bot, update.message)

async def cb_ap_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id):
        await q.answer("🚫  Access denied.", show_alert=True); return
    await show_ap_main(q)


# ── Users panel ────────────────────────────────────────────────────────────────

def ap_users_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍  Find User",    callback_data="ap_act_find"),
         InlineKeyboardButton("🚫  Ban User",     callback_data="ap_act_ban")],
        [InlineKeyboardButton("✅  Unban User",   callback_data="ap_act_unban"),
         InlineKeyboardButton("📋  View Bans",    callback_data="ap_act_listbans")],
        [InlineKeyboardButton("➕  Give Points",  callback_data="ap_act_give"),
         InlineKeyboardButton("➖  Take Points",  callback_data="ap_act_take")],
        [InlineKeyboardButton("🎯  Set Points",   callback_data="ap_act_set"),
         InlineKeyboardButton("🔄  Reset Streak", callback_data="ap_act_resetstreak")],
        [InlineKeyboardButton("🔙  Admin Panel",  callback_data="ap_main")],
    ])

async def cb_ap_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    text = (
        f"{LOGO}\n{D}\n\n"
        f"👥  <b>User Management</b>\n\n"
        f"Find users, manage bans, adjust points, and reset streaks.\n\n{D}"
    )
    try:
        if q.message.caption is not None:
            await q.edit_message_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=ap_users_kb())
        else:
            await q.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=ap_users_kb())
    except Exception: pass


# ── Admin management panel ─────────────────────────────────────────────────────

def ap_admins_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕  Add Admin",    callback_data="ap_act_addadmin"),
         InlineKeyboardButton("➖  Remove Admin", callback_data="ap_act_removeadmin")],
        [InlineKeyboardButton("📋  List Admins",  callback_data="ap_act_listadmins")],
        [InlineKeyboardButton("🔙  Admin Panel",  callback_data="ap_main")],
    ])

async def cb_ap_admins(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    text = (
        f"{LOGO}\n{D}\n\n"
        f"👑  <b>Admin Management</b>\n\n"
        f"<b>Permissions:</b>\n"
        f"  •  Any admin can add new admins\n"
        f"  •  You can remove admins you promoted\n"
        f"  •  Any admin can self-demote\n\n{D}"
    )
    try:
        if q.message.caption is not None:
            await q.edit_message_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=ap_admins_kb())
        else:
            await q.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=ap_admins_kb())
    except Exception: pass


# ── Tasks panel ────────────────────────────────────────────────────────────────

def ap_tasks_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕  Add Task",     callback_data="ap_act_addtask"),
         InlineKeyboardButton("📋  Manage Tasks", callback_data="ap_act_listtasks")],
        [InlineKeyboardButton("📊  Task Stats",   callback_data="ap_act_taskstats")],
        [InlineKeyboardButton("🔙  Admin Panel",  callback_data="ap_main")],
    ])

async def cb_ap_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    tasks = await get_all_tasks()
    active = sum(1 for t in tasks if t["active"])
    text = (
        f"{LOGO}\n{D}\n\n"
        f"📋  <b>Task Management</b>\n\n"
        f"Active tasks: <b>{active}</b>  /  Total: <b>{len(tasks)}</b>\n\n{D}"
    )
    try:
        if q.message.caption is not None:
            await q.edit_message_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=ap_tasks_kb())
        else:
            await q.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=ap_tasks_kb())
    except Exception: pass


# ── Rewards panel ──────────────────────────────────────────────────────────────

def ap_rewards_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕  Add Reward",     callback_data="ap_act_addreward"),
         InlineKeyboardButton("📋  Manage Rewards", callback_data="ap_act_listrewards")],
        [InlineKeyboardButton("🔙  Admin Panel",    callback_data="ap_main")],
    ])

async def cb_ap_rewards(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    rewards = await get_all_rewards()
    active  = sum(1 for r in rewards if r["active"])
    text = (
        f"{LOGO}\n{D}\n\n"
        f"🎁  <b>Reward Management</b>\n\n"
        f"Active rewards: <b>{active}</b>  /  Total: <b>{len(rewards)}</b>\n\n{D}"
    )
    try:
        if q.message.caption is not None:
            await q.edit_message_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=ap_rewards_kb())
        else:
            await q.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=ap_rewards_kb())
    except Exception: pass


# ── Stats panel ────────────────────────────────────────────────────────────────

def ap_stats_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊  Dashboard",     callback_data="ap_act_dashboard"),
         InlineKeyboardButton("🏆  Leaderboard",   callback_data="ap_act_adminlb")],
        [InlineKeyboardButton("📤  Export Users",  callback_data="ap_act_export")],
        [InlineKeyboardButton("🔙  Admin Panel",   callback_data="ap_main")],
    ])

async def cb_ap_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    text = f"{LOGO}\n{D}\n\n📊  <b>Statistics</b>\n\nView analytics, leaderboard, and export user data.\n\n{D}"
    try:
        if q.message.caption is not None:
            await q.edit_message_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=ap_stats_kb())
        else:
            await q.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=ap_stats_kb())
    except Exception: pass


# ── Lottery panel ──────────────────────────────────────────────────────────────

def ap_lottery_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎉  Draw Winner",   callback_data="ap_act_draw"),
         InlineKeyboardButton("📜  Draw History",  callback_data="ap_act_drawhistory")],
        [InlineKeyboardButton("🔙  Admin Panel",   callback_data="ap_main")],
    ])

async def cb_ap_lottery(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    history = await get_draw_history(1)
    last = ""
    if history:
        h = history[0]
        wname = f"@{h['username']}" if h["username"] else f"<code>{h['winner_id']}</code>"
        last = f"\nLast draw: {wname}  won  <b>{h['prize_pts']:,} pts</b>"
    text = f"{LOGO}\n{D}\n\n🎉  <b>Lottery</b>\n\nRun draws and view history.{last}\n\n{D}"
    try:
        if q.message.caption is not None:
            await q.edit_message_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=ap_lottery_kb())
        else:
            await q.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=ap_lottery_kb())
    except Exception: pass


# ── Broadcast panel ────────────────────────────────────────────────────────────

def ap_broadcast_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📣  Send Message",   callback_data="ap_act_broadcast"),
         InlineKeyboardButton("📢  Announcement",   callback_data="ap_act_announce")],
        [InlineKeyboardButton("🔙  Admin Panel",    callback_data="ap_main")],
    ])

async def cb_ap_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    users = await get_all_users()
    text = (
        f"{LOGO}\n{D}\n\n"
        f"📣  <b>Broadcast</b>\n\n"
        f"Will reach  <b>{len(users):,}</b> registered users.\n\n{D}"
    )
    try:
        if q.message.caption is not None:
            await q.edit_message_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=ap_broadcast_kb())
        else:
            await q.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=ap_broadcast_kb())
    except Exception: pass


# ── Direct Chat panel ─────────────────────────────────────────────────────────

def ap_directchat_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔  Watch a User",    callback_data="ap_act_watch"),
         InlineKeyboardButton("🔕  Stop Watching",   callback_data="ap_act_unwatch")],
        [InlineKeyboardButton("📋  Active Watches",  callback_data="ap_act_listwatches")],
        [InlineKeyboardButton("📨  DM a User",       callback_data="ap_act_dm")],
        [InlineKeyboardButton("🔙  Admin Panel",     callback_data="ap_main")],
    ])

async def cb_ap_directchat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    watches = await get_watches_for_admin(q.from_user.id)
    text = (
        f"{LOGO}\n{D}\n\n"
        f"💬  <b>Direct Chat</b>\n\n"
        f"Watch users to receive their bot messages directly.\n"
        f"Tap <b>↩️ Reply</b> on any forwarded message to reply.\n\n"
        f"📡  Active watches: <b>{len(watches)}</b>\n\n{D}"
    )
    try:
        if q.message.caption is not None:
            await q.edit_message_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=ap_directchat_kb())
        else:
            await q.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=ap_directchat_kb())
    except Exception: pass


# ── Guess Game panel ─────────────────────────────────────────────────────────

def ap_guessgame_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚽  Correct Score",    callback_data="ap_act_newscore"),
         InlineKeyboardButton("🎯  Correct Result",   callback_data="ap_act_newresult")],
        [InlineKeyboardButton("📋  Active Contest",   callback_data="ap_act_listcontests")],
        [InlineKeyboardButton("✅  Resolve Contests", callback_data="ap_act_resolve"),
         InlineKeyboardButton("🏆  Top Guessers",    callback_data="ap_act_topguess")],
        [InlineKeyboardButton("🔙  Admin Panel",      callback_data="ap_main")],
    ])

async def cb_ap_guessgame(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    contests = await get_open_contests()
    text = (
        f"{LOGO}\n{D}\n\n"
        f"🎯  <b>Guess Game</b>\n\n"
        f"Run Correct Score or Correct Result pools.\n\n"
        f"📡  Open contests: <b>{len(contests)}</b>\n\n{D}"
    )
    try:
        if q.message.caption is not None:
            await q.edit_message_caption(caption=text, parse_mode=ParseMode.HTML,
                                         reply_markup=ap_guessgame_kb())
        else:
            await q.edit_message_text(text=text, parse_mode=ParseMode.HTML,
                                      reply_markup=ap_guessgame_kb())
    except Exception: pass


# ── System panel ───────────────────────────────────────────────────────────────

def ap_system_kb(maint: bool) -> InlineKeyboardMarkup:
    maint_label = "🟢  Turn Maintenance OFF" if maint else "🔴  Turn Maintenance ON"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(maint_label, callback_data="ap_act_togglemaint")],
        [InlineKeyboardButton("🔙  Admin Panel", callback_data="ap_main")],
    ])

async def cb_ap_system(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    maint = "🔴  ON — Bot is in maintenance" if MAINTENANCE_MODE else "🟢  OFF — Bot is live"
    text = (
        f"{LOGO}\n{D}\n\n"
        f"⚙️  <b>System Settings</b>\n\n"
        f"🔧  Maintenance Mode: {maint}\n\n"
        f"<i>When maintenance is ON, non-admins see a maintenance screen.</i>\n\n{D}"
    )
    try:
        if q.message.caption is not None:
            await q.edit_message_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=ap_system_kb(MAINTENANCE_MODE))
        else:
            await q.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=ap_system_kb(MAINTENANCE_MODE))
    except Exception: pass


# ══════════════════════════════════════════════════════════════════════════════
#  Admin action callbacks (button triggers → ForceReply prompts or immediate)
# ══════════════════════════════════════════════════════════════════════════════

PROMPTS: dict[str, tuple[str, str, str]] = {
    # action: (title, body, example)
    "find":        ("Find User", "Enter the @username or numeric user ID.", "@username"),
    "ban":         ("Ban User",  "Enter @username and an optional reason.", "@username Reason here"),
    "unban":       ("Unban User","Enter the @username to unban.",            "@username"),
    "give":        ("Give Points","Enter @username and the amount to add.",  "@username 500"),
    "take":        ("Take Points","Enter @username and the amount to deduct.","@username 200"),
    "set":         ("Set Points", "Enter @username and the exact new balance.","@username 1000"),
    "resetstreak": ("Reset Streak","Enter the @username whose streak to reset.","@username"),
    "addadmin":    ("Add Admin",  "Enter the @username to promote to admin.",  "@username"),
    "removeadmin": ("Remove Admin","Enter the @username to demote.",            "@username"),
    "addtask":     ("Add Task",   "Format:  <code>Title | https://link | points</code>\n\nLeave link blank for app tasks.", "Join Channel | https://t.me/example | 200"),
    "addreward":   ("Add Reward", "Format:  <code>Title | Description | cost</code>", "VIP Badge | Exclusive badge | 5000"),
    "broadcast":   ("Broadcast",  "Type your message. It will be sent to <b>all users</b>.", "Your message here"),
    "announce":    ("Announcement","Type your announcement. It will be sent in a styled card.", "Big news!"),
    "draw":        ("Lottery Draw","Enter:  <code>prize_pts [min_pts]</code>\n\n<i>min_pts is optional (default: 0)</i>", "1000 500"),
    "watch":       ("Watch a User",    "Enter the @username to watch.\n\nEvery message they send to the bot will be forwarded directly to you.", "@username"),
    "unwatch":     ("Stop Watching",   "Enter the @username to stop watching.", "@username"),
    "dm":          ("DM a User — Step 1",  "Enter the @username of the user you want to message.", "@username"),
    "newscore":    ("New Score Contest — Step 1",
                   "Enter the name of <b>Team 1</b>.\n\n"
                   "This is the first team (left side of the score).",
                   "Ethiopia"),
    "newresult":   ("New Result Contest — Step 1",
                   "Enter the match / event title.\n\n"
                   "Users will tap one of: Win 1 / Draw / Win 2",
                   "Ethiopia vs Morocco — AFCON Final"),
    "resolve":     ("Resolve Contest — Step 1",
                   "Enter the <b>Contest ID</b> to resolve.\n\n"
                   "Tip: use 📋 Active Contests to find the ID.",
                   "12"),
    "topguess":    ("Top Guessers — Step 1",
                   "Enter the <b>Contest ID</b> to query.",
                   "12"),
}

async def cb_ap_act(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle all ap_act_* callbacks — show prompts or execute immediate actions."""
    global MAINTENANCE_MODE
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if not await is_admin(uid): await q.answer("🚫", show_alert=True); return

    action = q.data.replace("ap_act_", "")

    # ── Immediate actions (no input needed) ────────────────────────────────────

    if action == "listbans":
        bans = await get_all_bans()
        if not bans:
            await q.answer("✅  No banned users.", show_alert=True); return
        lines = []
        for b in bans:
            user = await get_user(b["user_id"])
            uname = f"@{user['username']}" if (user and user["username"]) else f"<code>{b['user_id']}</code>"
            date = b["created_at"].strftime("%d %b %Y") if b["created_at"] else "?"
            lines.append(f"🚫  {uname}  —  <i>{b['reason'] or '—'}</i>  ({date})")
        await q.message.reply_text(
            f"{LOGO}\n{D}\n\n🚫  <b>Banned Users ({len(bans)})</b>\n\n" + "\n".join(lines) + f"\n\n{D}",
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙  Back", callback_data="ap_users")
            ]])
        )
        return

    if action == "listadmins":
        admins = await get_all_admins()
        lines = []
        for a in admins:
            user = await get_user(a["user_id"])
            uname = f"@{user['username']}" if (user and user["username"]) else f"<code>{a['user_id']}</code>"
            added = a["created_at"].strftime("%d %b %Y") if a["created_at"] else "?"
            lines.append(f"👑  {uname}  —  added {added}")
        text = (
            f"{LOGO}\n{D}\n\n👑  <b>Current Admins</b>\n\n"
            f"🌟  Primary:  <code>{ADMIN_USER_ID}</code>\n\n"
            + ("\n".join(lines) if lines else "<i>No sub-admins yet.</i>")
            + f"\n\n{D}"
        )
        await q.message.reply_text(text, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back", callback_data="ap_admins")]]))
        return

    if action == "listtasks":
        tasks = await get_all_tasks()
        if not tasks:
            await q.answer("📭  No tasks yet.", show_alert=True); return
        rows = []
        for t in tasks:
            status = "✅" if t["active"] else "🔴"
            tog    = "off" if t["active"] else "on"
            rows.append([InlineKeyboardButton(
                f"{status}  #{t['id']} {t['title']}  (+{t['points']} pts)",
                callback_data=f"adm_task_toggle_{t['id']}_{tog}")])
        rows.append([InlineKeyboardButton("🗑  Delete a Task", callback_data="ap_act_deltask")])
        rows.append([InlineKeyboardButton("🔙  Back",          callback_data="ap_tasks")])
        await q.message.reply_text(
            f"{LOGO}\n{D}\n\n📋  <b>All Tasks</b>  — tap to toggle on/off:\n\n{D}",
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
        return

    if action == "deltask":
        tasks = await get_all_tasks()
        if not tasks:
            await q.answer("📭  No tasks.", show_alert=True); return
        rows = [[InlineKeyboardButton(f"🗑  #{t['id']} {t['title']}", callback_data=f"ap_del_task_{t['id']}")] for t in tasks]
        rows.append([InlineKeyboardButton("🔙  Back", callback_data="ap_tasks")])
        await q.message.reply_text(
            f"{LOGO}\n{D}\n\n🗑️  <b>Delete Task</b>\n\n<i>This is permanent and removes all completions.</i>\n\n{D}",
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
        return

    if action == "listrewards":
        rewards = await get_all_rewards()
        if not rewards:
            await q.answer("📭  No rewards yet.", show_alert=True); return
        rows = []
        for r in rewards:
            status = "✅" if r["active"] else "🔴"
            tog    = "off" if r["active"] else "on"
            rows.append([InlineKeyboardButton(
                f"{status}  #{r['id']} {r['title']}  ({r['cost']:,} pts)",
                callback_data=f"adm_reward_toggle_{r['id']}_{tog}")])
        rows.append([InlineKeyboardButton("🗑  Delete a Reward", callback_data="ap_act_delreward")])
        rows.append([InlineKeyboardButton("🔙  Back",             callback_data="ap_rewards")])
        await q.message.reply_text(
            f"{LOGO}\n{D}\n\n🎁  <b>All Rewards</b>  — tap to toggle:\n\n{D}",
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
        return

    if action == "delreward":
        rewards = await get_all_rewards()
        if not rewards:
            await q.answer("📭  No rewards.", show_alert=True); return
        rows = [[InlineKeyboardButton(f"🗑  #{r['id']} {r['title']}", callback_data=f"ap_del_reward_{r['id']}")] for r in rewards]
        rows.append([InlineKeyboardButton("🔙  Back", callback_data="ap_rewards")])
        await q.message.reply_text(
            f"{LOGO}\n{D}\n\n🗑️  <b>Delete Reward</b>\n\n<i>This is permanent.</i>\n\n{D}",
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
        return

    if action == "dashboard":
        tasks = await get_all_tasks(); rewards = await get_all_rewards()
        users = await get_all_users_full(); bans = await get_all_bans()
        admins = await get_all_admins()
        total_pts = sum(u["points"] for u in users)
        avg_pts   = total_pts // len(users) if users else 0
        top = users[0] if users else None
        top_name = (f"@{top['username']}" if (top and top["username"]) else f"<code>{top['id']}</code>") if top else "—"
        draws = await get_draw_history(1)
        draws_run = len(draws)
        await q.message.reply_text(
            f"{LOGO}\n{D}\n\n"
            f"📊  <b>Dashboard</b>\n\n"
            f"{D2}\n"
            f"👥  Users:          <b>{len(users):,}</b>   🚫 Banned: <b>{len(bans)}</b>\n"
            f"💰  Total pts issued: <b>{total_pts:,}</b>\n"
            f"📈  Avg pts/user:     <b>{avg_pts:,}</b>\n"
            f"🏆  Top player:       {top_name}\n"
            f"{D2}\n"
            f"📋  Tasks:    {sum(1 for t in tasks if t['active'])} active / {len(tasks)}\n"
            f"🎁  Rewards:  {sum(1 for r in rewards if r['active'])} active / {len(rewards)}\n"
            f"👑  Admins:   {len(admins) + (1 if ADMIN_USER_ID else 0)}\n"
            f"🎉  Draws run: {draws_run}\n\n{D}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back", callback_data="ap_stats")]]))
        return

    if action == "adminlb":
        top = await get_leaderboard(20)
        lines = []
        for i, u in enumerate(top):
            medal = RANK_MEDALS[i] if i < 3 else f"#{i+1:2d}"
            uname = f"@{u['username']}" if u["username"] else f"<code>{u['id']}</code>"
            lines.append(f"{medal}  {lv_badge(u['level'])}  {uname}  —  {u['points']:,} pts")
        await q.message.reply_text(
            f"{LOGO}\n{D}\n\n🏆  <b>Top 20 Leaderboard</b>\n\n" + "\n".join(lines or ["No users yet."]) + f"\n\n{D}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back", callback_data="ap_stats")]]))
        return

    if action == "export":
        users = await get_all_users_full()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id","username","lang","points","level","streak","referral_count","joined"])
        for u in users:
            writer.writerow([u["id"], u["username"] or "", u["lang"] or "en", u["points"],
                             u["level"], u.get("streak",0) or 0, u.get("referral_count",0) or 0,
                             u["created_at"].strftime("%Y-%m-%d %H:%M") if u["created_at"] else ""])
        output.seek(0)
        filename = f"users_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        await ctx.bot.send_document(
            q.from_user.id, document=io.BytesIO(output.getvalue().encode("utf-8")), filename=filename,
            caption=f"📤  <b>User Export</b>  —  {len(users):,} users", parse_mode=ParseMode.HTML)
        return

    if action == "drawhistory":
        history = await get_draw_history(10)
        if not history:
            await q.answer("📭  No draws run yet.", show_alert=True); return
        lines = []
        for h in history:
            wname = f"@{h['username']}" if h["username"] else f"<code>{h['winner_id']}</code>"
            date  = h["created_at"].strftime("%d %b %Y %H:%M") if h["created_at"] else "?"
            lines.append(f"🎉  {wname}  won  <b>{h['prize_pts']:,} pts</b>  —  {date}")
        await q.message.reply_text(
            f"{LOGO}\n{D}\n\n🎉  <b>Draw History</b>\n\n" + "\n".join(lines) + f"\n\n{D}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back", callback_data="ap_lottery")]]))
        return

    if action == "togglemaint":
        global MAINTENANCE_MODE
        MAINTENANCE_MODE = not MAINTENANCE_MODE
        await set_setting("maintenance", "1" if MAINTENANCE_MODE else "0")
        status = "🔴  ENABLED — users see maintenance screen" if MAINTENANCE_MODE else "🟢  DISABLED — bot is live"
        await q.answer(f"Maintenance {status}", show_alert=True)
        await cb_ap_system(update, ctx)
        return

    if action == "taskstats":
        tasks = await get_all_tasks()
        total_users = len(await get_all_users())
        if not tasks:
            await q.answer("📭  No tasks yet.", show_alert=True); return
        lines = []
        for t in tasks:
            count = await get_task_completion_count(t["id"])
            pct   = int(count / total_users * 100) if total_users > 0 else 0
            bar   = progress_bar(count, total_users, 8)
            status = "✅" if t["active"] else "🔴"
            lines.append(f"{status}  <b>#{t['id']} {t['title']}</b>\n    {bar}  {count}/{total_users}  ({pct}%)")
        await q.message.reply_text(
            f"{LOGO}\n{D}\n\n📊  <b>Task Completion Stats</b>\n\n" + "\n\n".join(lines) + f"\n\n{D}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back", callback_data="ap_tasks")]]))
        return

    if action == "listwatches":
        watches = await get_watches_for_admin(uid)
        if not watches:
            await q.answer("📭  No active watches.", show_alert=True); return
        lines = []
        for w in watches:
            user = await get_user(w["target_user_id"])
            uname = f"@{user['username']}" if (user and user.get("username")) else f"<code>{w['target_user_id']}</code>"
            since = w["created_at"].strftime("%d %b %Y") if w.get("created_at") else "?"
            lines.append(f"🔔  {uname}  <i>(since {since})</i>")
        await q.message.reply_text(
            f"{LOGO}\n{D}\n\n💬  <b>Active Watches ({len(watches)})</b>\n\n"
            + "\n".join(lines)
            + f"\n\n<i>Use 🔕 Stop Watching to remove a watch.</i>\n\n{D}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back", callback_data="ap_directchat")]]))
        return

    if action == "listcontests":
        contests = await get_open_contests()
        if not contests:
            await q.answer("📭  No open contests right now.", show_alert=True); return
        lines = []
        stop_btns: list[InlineKeyboardButton] = []
        for c in contests:
            entries = await get_contest_entry_count(c["id"])
            dl = c["deadline"].strftime("%d %b %H:%M UTC") if c.get("deadline") else "?"
            ctype = "⚽ Score" if c["contest_type"] == "score" else "🎯 Result"
            lines.append(
                f"<b>#{c['id']}</b>  {ctype}\n"
                f"  📝 {c['question']}\n"
                f"  ⏰ Closes: {dl}  |  👥 {entries} entries")
            stop_btns.append(InlineKeyboardButton(f"⛔ Stop #{c['id']}", callback_data=f"stop_contest_{c['id']}"))
        stop_rows = [stop_btns[i:i+3] for i in range(0, len(stop_btns), 3)]
        kb = InlineKeyboardMarkup(stop_rows + [[InlineKeyboardButton("🔙  Back", callback_data="ap_guessgame")]])
        await q.message.reply_text(
            f"{LOGO}\n{D}\n\n🎯  <b>Open Contests ({len(contests)})</b>\n\n"
            + "\n\n".join(lines)
            + f"\n\n<i>Tap ⛔ Stop to close a contest early.</i>\n\n{D}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb)
        return

    # ── Actions that need text input → ForceReply prompt ─────────────────────
    if action in PROMPTS:
        title, body, example = PROMPTS[action]
        ctx.user_data["ap_action"] = action
        ctx.user_data["ap_step"]   = 1
        ctx.user_data["ap_data"]   = {}
        await admin_prompt(ctx.bot, q.from_user.id, title, body, example)


# ── Delete task / reward inline confirmations ──────────────────────────────────

async def cb_ap_del_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): return
    tid = int(q.data.split("_")[3])
    task = await get_task_by_id(tid)
    if not task:
        await q.answer("⚠️  Task not found.", show_alert=True); return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🗑  Yes, delete #{tid}", callback_data=f"ap_confirm_deltask_{tid}"),
         InlineKeyboardButton("❌  Cancel",               callback_data="ap_act_listtasks")],
    ])
    await q.message.reply_text(
        f"{LOGO}\n{D}\n\n⚠️  <b>Confirm Delete</b>\n\n"
        f"Delete task  <b>#{tid}: {task['title']}</b>?\n\n"
        f"<i>This removes all user completions for this task.</i>\n\n{D}",
        parse_mode=ParseMode.HTML, reply_markup=kb)

async def cb_ap_confirm_deltask(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): return
    tid = int(q.data.split("_")[3])
    task = await get_task_by_id(tid)
    await delete_task(tid)
    await q.edit_message_text(
        f"✅  Task  <b>#{tid}: {task['title'] if task else tid}</b>  deleted.",
        parse_mode=ParseMode.HTML)

async def cb_ap_del_reward(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): return
    rid = int(q.data.split("_")[3])
    async with pool.acquire() as conn:
        reward = await conn.fetchrow("SELECT * FROM rewards WHERE id=$1", rid)
    if not reward:
        await q.answer("⚠️  Reward not found.", show_alert=True); return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🗑  Yes, delete #{rid}", callback_data=f"ap_confirm_delreward_{rid}"),
         InlineKeyboardButton("❌  Cancel",               callback_data="ap_act_listrewards")],
    ])
    await q.message.reply_text(
        f"{LOGO}\n{D}\n\n⚠️  <b>Confirm Delete</b>\n\nDelete reward  <b>#{rid}: {reward['title']}</b>?\n\n{D}",
        parse_mode=ParseMode.HTML, reply_markup=kb)

async def cb_ap_confirm_delreward(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): return
    rid = int(q.data.split("_")[3])
    async with pool.acquire() as conn:
        reward = await conn.fetchrow("SELECT title FROM rewards WHERE id=$1", rid)
    await delete_reward(rid)
    await q.edit_message_text(
        f"✅  Reward  <b>#{rid}: {reward['title'] if reward else rid}</b>  deleted.",
        parse_mode=ParseMode.HTML)

async def cb_adm_task_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    parts = q.data.split("_")
    tid, new_state = int(parts[3]), parts[4] == "on"
    await toggle_task(tid, new_state)
    await q.answer("✅  Enabled" if new_state else "🔴  Disabled", show_alert=True)
    tasks = await get_all_tasks()
    rows = []
    for t in tasks:
        status = "✅" if t["active"] else "🔴"
        tog    = "off" if t["active"] else "on"
        rows.append([InlineKeyboardButton(f"{status}  #{t['id']} {t['title']}  (+{t['points']} pts)", callback_data=f"adm_task_toggle_{t['id']}_{tog}")])
    rows.append([InlineKeyboardButton("🗑  Delete a Task", callback_data="ap_act_deltask")])
    rows.append([InlineKeyboardButton("🔙  Back",          callback_data="ap_tasks")])
    await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(rows))

async def cb_adm_reward_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    parts = q.data.split("_")
    rid, new_state = int(parts[3]), parts[4] == "on"
    await toggle_reward(rid, new_state)
    await q.answer("✅  Enabled" if new_state else "🔴  Disabled", show_alert=True)
    rewards = await get_all_rewards()
    rows = []
    for r in rewards:
        status = "✅" if r["active"] else "🔴"
        tog    = "off" if r["active"] else "on"
        rows.append([InlineKeyboardButton(f"{status}  #{r['id']} {r['title']}  ({r['cost']:,} pts)", callback_data=f"adm_reward_toggle_{r['id']}_{tog}")])
    rows.append([InlineKeyboardButton("🗑  Delete a Reward", callback_data="ap_act_delreward")])
    rows.append([InlineKeyboardButton("🔙  Back",             callback_data="ap_rewards")])
    await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(rows))


# ══════════════════════════════════════════════════════════════════════════════
#  Admin text input router (catches ForceReply replies)
# ══════════════════════════════════════════════════════════════════════════════

async def cb_dm_reply_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin taps ↩️ Reply on a forwarded user message."""
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if not await is_admin(uid): await q.answer("🚫", show_alert=True); return
    target_id = int(q.data.replace("dm_reply_", ""))
    user = await get_user(target_id)
    label = f"@{user['username']}" if (user and user.get("username")) else f"ID:{target_id}"
    ctx.user_data["ap_action"] = "dm_reply"
    ctx.user_data["ap_step"]   = 1
    ctx.user_data["ap_data"]   = {"target_id": target_id, "label": label}
    await admin_prompt(ctx.bot, uid,
        f"↩️  Reply to {label}",
        f"Type your reply. It will be sent privately to <b>{label}</b>.\n\nSupports HTML formatting.",
        "Your reply here…")


# ── Guess Game user callbacks ──────────────────────────────────────────────────

def _score_dialpad(prompt_text: str, cb_prefix: str, cid: int, extra: str = "") -> tuple[str, InlineKeyboardMarkup]:
    """Build the dial-pad message and keyboard for score selection."""
    msg = (
        f"{LOGO}\n{D}\n\n"
        f"⚽  <b>Score Prediction</b>\n\n"
        + (f"{extra}\n\n" if extra else "")
        + f"🎯  {prompt_text}\n\n"
        f"{D2}\n"
        f"<i>Tap a number below:</i>"
    )
    rows = [
        [
            InlineKeyboardButton("0", callback_data=f"{cb_prefix}_{cid}_0"),
            InlineKeyboardButton("1", callback_data=f"{cb_prefix}_{cid}_1"),
            InlineKeyboardButton("2", callback_data=f"{cb_prefix}_{cid}_2"),
            InlineKeyboardButton("3", callback_data=f"{cb_prefix}_{cid}_3"),
            InlineKeyboardButton("4", callback_data=f"{cb_prefix}_{cid}_4"),
        ],
        [
            InlineKeyboardButton("5", callback_data=f"{cb_prefix}_{cid}_5"),
            InlineKeyboardButton("6", callback_data=f"{cb_prefix}_{cid}_6"),
            InlineKeyboardButton("7", callback_data=f"{cb_prefix}_{cid}_7"),
            InlineKeyboardButton("8", callback_data=f"{cb_prefix}_{cid}_8"),
            InlineKeyboardButton("9", callback_data=f"{cb_prefix}_{cid}_9"),
        ],
        [
            InlineKeyboardButton("🔟  10+", callback_data=f"{cb_prefix}_{cid}_10"),
        ],
    ]
    return msg, InlineKeyboardMarkup(rows)


async def cb_guess_participate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User taps '🏆 Participate' — show dial pad for Team 1 score."""
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    parts = q.data.split("_")          # guess_participate_{cid}
    try:
        cid = int(parts[2])
    except (IndexError, ValueError):
        await q.answer("⚠️  Invalid contest.", show_alert=True); return
    contest = await get_contest(cid)
    if not contest or contest["status"] != "open":
        await q.answer("⏰  This contest is already closed.", show_alert=True); return
    now = datetime.now(timezone.utc)
    deadline = contest["deadline"].replace(tzinfo=timezone.utc) if contest.get("deadline") else now
    if now > deadline:
        await q.answer("⏰  The deadline has passed.", show_alert=True); return
    existing = await get_user_guess(cid, uid)
    if existing:
        await q.answer(f"✅  Already submitted: {existing['guess']}", show_alert=True); return
    team1 = contest.get("team1") or "Team 1"
    team2 = contest.get("team2") or "Team 2"
    dl_str = deadline.strftime("%d %b %Y %H:%M UTC")
    header = f"🔵 <b>{team1}</b>  vs  🔴 <b>{team2}</b>\n⏰  Closes: <b>{dl_str}</b>"
    prompt = f"How many goals will <b>{team1}</b> score?"
    msg, kb = _score_dialpad(prompt, "score_t1", cid, header)
    await q.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb)


async def cb_score_t1(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User selects Team 1 score — show dial pad for Team 2 score."""
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    parts = q.data.split("_")          # score_t1_{cid}_{val}
    try:
        cid  = int(parts[2])
        val  = parts[3]                # "0"-"10"
    except (IndexError, ValueError):
        await q.answer("⚠️  Invalid selection.", show_alert=True); return
    contest = await get_contest(cid)
    if not contest or contest["status"] != "open":
        await q.answer("⏰  This contest is closed.", show_alert=True); return
    now = datetime.now(timezone.utc)
    deadline = contest["deadline"].replace(tzinfo=timezone.utc) if contest.get("deadline") else now
    if now > deadline:
        await q.answer("⏰  The deadline has passed.", show_alert=True); return
    existing = await get_user_guess(cid, uid)
    if existing:
        await q.answer(f"✅  Already submitted: {existing['guess']}", show_alert=True); return
    team1  = contest.get("team1") or "Team 1"
    team2  = contest.get("team2") or "Team 2"
    label1 = f"{val}+" if val == "10" else val
    header = (
        f"🔵 <b>{team1}</b>  vs  🔴 <b>{team2}</b>\n\n"
        f"✅  <b>{team1}:</b>  {label1}  goal{'s' if val != '1' else ''}"
    )
    prompt = f"Now, how many goals will <b>{team2}</b> score?"
    msg, kb = _score_dialpad(prompt, f"score_t2_{val}", cid, header)
    try:
        await q.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        await q.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb)


async def cb_score_t2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User selects Team 2 score — submit the full guess."""
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    # callback: score_t2_{t1val}_{cid}_{t2val}
    parts = q.data.split("_")
    try:
        t1val = parts[2]
        cid   = int(parts[3])
        t2val = parts[4]
    except (IndexError, ValueError):
        await q.answer("⚠️  Invalid selection.", show_alert=True); return
    contest = await get_contest(cid)
    if not contest or contest["status"] != "open":
        await q.answer("⏰  This contest is closed.", show_alert=True); return
    now = datetime.now(timezone.utc)
    deadline = contest["deadline"].replace(tzinfo=timezone.utc) if contest.get("deadline") else now
    if now > deadline:
        await q.answer("⏰  The deadline has passed.", show_alert=True); return
    existing = await get_user_guess(cid, uid)
    if existing:
        await q.answer(f"✅  Already submitted: {existing['guess']}", show_alert=True); return
    guess = f"{t1val}-{t2val}"
    await submit_guess(cid, uid, guess)
    team1  = contest.get("team1") or "Team 1"
    team2  = contest.get("team2") or "Team 2"
    label1 = f"{t1val}+" if t1val == "10" else t1val
    label2 = f"{t2val}+" if t2val == "10" else t2val
    result_msg = (
        f"{LOGO}\n{D}\n\n"
        f"✅  <b>Prediction Submitted!</b>\n\n"
        f"⚽  <b>{team1}</b>  <code>{label1}</code>  —  <code>{label2}</code>  <b>{team2}</b>\n\n"
        f"Good luck! 🍀\n\n{D}"
    )
    try:
        await q.edit_message_text(result_msg, parse_mode=ParseMode.HTML)
    except Exception:
        await q.message.reply_text(result_msg, parse_mode=ParseMode.HTML)


async def cb_guess_result(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User taps Win1/Draw/Win2 on a result-type contest."""
    q = update.callback_query
    await q.answer()                   # always clear the spinner immediately
    uid = q.from_user.id
    parts = q.data.split("_")          # guess_result_{cid}_{choice}
    try:
        cid    = int(parts[2])
        choice = parts[3]              # win1 | draw | win2
    except (IndexError, ValueError):
        await q.message.reply_text("⚠️  Invalid data."); return
    contest = await get_contest(cid)
    if not contest or contest["status"] != "open":
        await q.message.reply_text("⏰  This contest is closed."); return
    now = datetime.now(timezone.utc)
    deadline = contest["deadline"].replace(tzinfo=timezone.utc) if contest.get("deadline") else now
    if now > deadline:
        await q.message.reply_text("⏰  Deadline has passed."); return
    labels = {"win1": "1️⃣  Win 1", "draw": "🤝  Draw", "win2": "2️⃣  Win 2"}
    existing = await get_user_guess(cid, uid)
    if existing:
        prev = labels.get(existing["guess"], existing["guess"])
        await q.message.reply_text(f"✅  You already picked: <b>{prev}</b>", parse_mode=ParseMode.HTML)
        return
    await submit_guess(cid, uid, choice)
    user = await get_user(uid)
    lang = user["lang"] if user else "en"
    t = lc(lang)
    label = labels.get(choice, choice)
    confirm_text = t["contest_chose"].format(choice=label)
    await q.message.reply_text(confirm_text, parse_mode=ParseMode.HTML)


def _admin_score_kb(cb_prefix: str, cid: int) -> InlineKeyboardMarkup:
    """Number-pad keyboard for admin score resolution."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("0", callback_data=f"{cb_prefix}_{cid}_0"),
         InlineKeyboardButton("1", callback_data=f"{cb_prefix}_{cid}_1"),
         InlineKeyboardButton("2", callback_data=f"{cb_prefix}_{cid}_2"),
         InlineKeyboardButton("3", callback_data=f"{cb_prefix}_{cid}_3"),
         InlineKeyboardButton("4", callback_data=f"{cb_prefix}_{cid}_4")],
        [InlineKeyboardButton("5", callback_data=f"{cb_prefix}_{cid}_5"),
         InlineKeyboardButton("6", callback_data=f"{cb_prefix}_{cid}_6"),
         InlineKeyboardButton("7", callback_data=f"{cb_prefix}_{cid}_7"),
         InlineKeyboardButton("8", callback_data=f"{cb_prefix}_{cid}_8"),
         InlineKeyboardButton("9", callback_data=f"{cb_prefix}_{cid}_9")],
        [InlineKeyboardButton("🔟  10+", callback_data=f"{cb_prefix}_{cid}_10")],
    ])


async def cb_stop_contest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin taps ⛔ Stop #{cid} — immediately closes a contest."""
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    cid = int(q.data.split("_")[2])
    contest = await get_contest(cid)
    if not contest:
        await q.answer(f"⚠️  Contest #{cid} not found.", show_alert=True); return
    async with pool.acquire() as conn:
        await conn.execute("UPDATE guess_contests SET status='closed' WHERE id=$1", cid)
    entries = await get_contest_entry_count(cid)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅  Resolve Now", callback_data="ap_act_resolve")],
        [InlineKeyboardButton("🔙  Back", callback_data="ap_guessgame")],
    ])
    try:
        await q.edit_message_text(
            f"{LOGO}\n{D}\n\n"
            f"⛔  <b>Contest #{cid} Stopped</b>\n\n"
            f"📝  {contest['question']}\n"
            f"👥  {entries:,} entries collected\n\n"
            f"<i>Use ✅ Resolve Now to enter the correct answer and find winners.</i>\n\n{D}",
            parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        await q.message.reply_text(
            f"{LOGO}\n{D}\n\n⛔  <b>Contest #{cid} Stopped</b>\n\n"
            f"📝  {contest['question']}\n"
            f"👥  {entries:,} entries collected\n\n{D}",
            parse_mode=ParseMode.HTML, reply_markup=kb)


async def cb_resolve_t1(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin picks Team 1 correct score — show Team 2 pad."""
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    parts = q.data.split("_")          # resolve_t1_{cid}_{val}
    cid  = int(parts[2])
    val  = parts[3]
    contest = await get_contest(cid)
    if not contest:
        await q.answer("⚠️  Contest not found.", show_alert=True); return
    team1 = contest.get("team1") or "Team 1"
    team2 = contest.get("team2") or "Team 2"
    label1 = f"{val}+" if val == "10" else val
    kb = _admin_score_kb(f"resolve_t2_{val}", cid)
    try:
        await q.edit_message_text(
            f"{LOGO}\n{D}\n\n"
            f"✅  <b>Resolve Contest #{cid}</b>\n\n"
            f"📝  <b>{contest['question']}</b>\n\n"
            f"✔️  <b>{team1}:</b>  {label1}  goal{'s' if val != '1' else ''}\n\n"
            f"Now tap the correct goals for  <b>{team2}</b>:\n\n{D}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb)
    except Exception:
        await q.message.reply_text(
            f"Now enter goals for  <b>{team2}</b>:",
            parse_mode=ParseMode.HTML, reply_markup=kb)


async def cb_resolve_t2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin picks Team 2 correct score — resolve contest, show count + See Top 10."""
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    parts = q.data.split("_")          # resolve_t2_{t1val}_{cid}_{t2val}
    t1val = parts[2]
    cid   = int(parts[3])
    t2val = parts[4]
    correct = f"{t1val}-{t2val}"
    await resolve_contest(cid, correct)
    contest = await get_contest(cid)
    winners = await get_correct_guessers(cid, 500)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏆  See Top 10", callback_data=f"ap_showtop_{cid}")],
        [InlineKeyboardButton("🔙  Guess Game", callback_data="ap_guessgame")],
    ])
    try:
        await q.edit_message_text(
            f"{LOGO}\n{D}\n\n"
            f"✅  <b>Contest #{cid} Resolved!</b>\n\n"
            f"📝  {contest['question']}\n"
            f"⚽  Correct score: <b>{correct}</b>\n\n"
            f"🎯  Correct guessers: <b>{len(winners)}</b>\n\n{D}",
            parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        await q.message.reply_text(
            f"✅  Contest #{cid} resolved! Score: <b>{correct}</b>\n"
            f"🎯  Correct guessers: <b>{len(winners)}</b>",
            parse_mode=ParseMode.HTML, reply_markup=kb)


async def cb_resolve_result(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin picks Win1/Draw/Win2 — resolve result contest, show count + See Top 10."""
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    parts = q.data.split("_")          # resolve_result_{cid}_{outcome}
    cid     = int(parts[2])
    outcome = parts[3]
    await resolve_contest(cid, outcome)
    contest = await get_contest(cid)
    winners = await get_correct_guessers(cid, 500)
    labels  = {"win1": "Win 1 🥇", "draw": "Draw 🤝", "win2": "Win 2 🥈"}
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏆  See Top 10", callback_data=f"ap_showtop_{cid}")],
        [InlineKeyboardButton("🔙  Guess Game", callback_data="ap_guessgame")],
    ])
    try:
        await q.edit_message_text(
            f"{LOGO}\n{D}\n\n"
            f"✅  <b>Contest #{cid} Resolved!</b>\n\n"
            f"📝  {contest['question']}\n"
            f"🎯  Result: <b>{labels.get(outcome, outcome)}</b>\n\n"
            f"✔️  Correct guessers: <b>{len(winners)}</b>\n\n{D}",
            parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        await q.message.reply_text(
            f"✅  Contest #{cid} resolved — <b>{labels.get(outcome, outcome)}</b>\n"
            f"✔️  Correct guessers: <b>{len(winners)}</b>",
            parse_mode=ParseMode.HTML, reply_markup=kb)


async def cb_ap_showtop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin taps 🏆 See Top 10 — display ranked winners then purge losers."""
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    cid = int(q.data.split("_")[2])
    contest = await get_contest(cid)
    if not contest:
        await q.answer(f"⚠️  Contest #{cid} not found.", show_alert=True); return
    winners = await get_correct_guessers(cid, 10)
    await purge_losers(cid, 10)
    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Guess Game", callback_data="ap_guessgame")]])
    if not winners:
        try:
            await q.edit_message_text(
                f"{LOGO}\n{D}\n\n⚠️  No correct guessers for contest #{cid}.\n\n{D}",
                parse_mode=ParseMode.HTML, reply_markup=back_kb)
        except Exception:
            await q.message.reply_text(
                f"⚠️  No correct guessers for contest #{cid}.",
                parse_mode=ParseMode.HTML, reply_markup=back_kb)
        return
    lines = []
    for i, w in enumerate(winners):
        uname = f"@{w['username']}" if w.get("username") else f"<code>{w['user_id']}</code>"
        t_str = w["submitted_at"].strftime("%H:%M:%S") if w.get("submitted_at") else "?"
        medal = RANK_MEDALS[i] if i < len(RANK_MEDALS) else f"#{i+1}"
        lines.append(f"{medal}  {uname} — <b>{w['guess']}</b>  <i>at {t_str}</i>")
    text = (
        f"{LOGO}\n{D}\n\n"
        f"🏆  <b>Top {len(winners)} Correct Guessers</b>\n"
        f"📋  Contest #{cid}: <b>{contest['question']}</b>\n"
        f"✅  Answer: <b>{contest.get('correct_answer', '—')}</b>\n\n"
        + "\n".join(lines) + "\n\n"
        f"{D2}\n"
        f"🗑  <i>All incorrect entries removed. Only these {len(winners)} winner(s) remain in the database.</i>\n\n{D}"
    )
    action_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📣  Share Top 10 to All Users", callback_data=f"ap_share_top10_{cid}")],
        [InlineKeyboardButton("📲  Ask Winners for Fala Number", callback_data=f"ask_fala_{cid}")],
        [InlineKeyboardButton("🔙  Guess Game", callback_data="ap_guessgame")],
    ])
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=action_kb)
    except Exception:
        await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=action_kb)


async def cb_ask_fala_number(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin taps 'Ask Winners for Fala Number' — DM each winner asking for their account."""
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): return
    cid = int(q.data.split("_")[2])
    contest = await get_contest(cid)
    if not contest:
        await q.answer("⚠️  Contest not found.", show_alert=True); return
    winners = await get_correct_guessers(cid, 10)
    if not winners:
        await q.answer("⚠️  No winners found.", show_alert=True); return

    admin_rows = await get_all_admins()
    admin_ids  = {row["admin_id"] for row in admin_rows}
    if ADMIN_USER_ID: admin_ids.add(ADMIN_USER_ID)

    sent = 0
    for i, w in enumerate(winners):
        uid  = w["user_id"]
        rank = i + 1
        _fala_awaiting[uid] = {
            "cid":      cid,
            "rank":     rank,
            "guess":    w["guess"],
            "question": contest["question"],
            "admin_ids": list(admin_ids),
        }
        try:
            await ctx.bot.send_message(
                uid,
                f"🎉  <b>Congratulations!</b>\n\n"
                f"You won the contest by choosing <b>{w['guess']}</b>.\n\n"
                f"To deposit your prize, please send us the phone number linked to "
                f"your <b>Falabet account</b>.\n\n"
                f"Format:\n"
                f"  • <code>+251912345678</code>\n"
                f"  • <code>0912345678</code>  /  <code>0712345678</code>\n\n"
                f"Simply reply to this message with your number. 📲",
                parse_mode=ParseMode.HTML)
            sent += 1
        except Exception:
            _fala_awaiting.pop(uid, None)
    await q.message.reply_text(
        f"📲  <b>Fala Number Request Sent</b>\n\n"
        f"Prompted <b>{sent}</b> of {len(winners)} winner(s).\n"
        f"Their replies will be forwarded to all admins.",
        parse_mode=ParseMode.HTML)


async def cb_reward_sent(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin taps 'Reward Sent' — notify the winner and update the message."""
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): return
    uid = int(q.data.split("_")[2])
    try:
        await ctx.bot.send_message(
            uid,
            f"🎉  <b>Reward Deposited!</b>\n\n"
            f"Your prize has been successfully deposited to your Falabet account. "
            f"Thank you for participating! 🍀",
            parse_mode=ParseMode.HTML)
    except Exception:
        pass
    try:
        await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅  Reward Sent", callback_data="noop")
        ]]))
    except Exception:
        pass
    await q.answer("✅  Reward notification sent!", show_alert=True)


async def cb_ap_share_top10(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Broadcast the top-10 winners list to every registered user."""
    q = update.callback_query; await q.answer()
    if not await is_admin(q.from_user.id): await q.answer("🚫", show_alert=True); return
    cid = int(q.data.split("_")[3])
    contest = await get_contest(cid)
    if not contest:
        await q.answer(f"⚠️  Contest #{cid} not found.", show_alert=True); return
    winners = await get_correct_guessers(cid, 10)
    if not winners:
        await q.answer("⚠️  No winners to share yet.", show_alert=True); return

    lines = []
    for i, w in enumerate(winners):
        uname = f"@{w['username']}" if w.get("username") else f"👤 #{w['user_id']}"
        t_str = w["submitted_at"].strftime("%H:%M:%S") if w.get("submitted_at") else "?"
        medal = RANK_MEDALS[i] if i < len(RANK_MEDALS) else f"#{i+1}"
        lines.append(f"{medal}  {uname}  <i>({t_str})</i>")

    broadcast_text = (
        f"{LOGO}\n{D}\n\n"
        f"🏆  <b>Contest Results!</b>\n\n"
        f"⚽  <b>{contest['question']}</b>\n"
        f"✅  Final score / result: <b>{contest.get('correct_answer', '—')}</b>\n\n"
        f"{D2}\n"
        f"🎉  <b>Top {len(winners)} Winners</b>  (ranked by fastest correct guess)\n\n"
        + "\n".join(lines) + "\n\n"
        f"{D2}\n"
        f"🍀  <i>Congratulations to all winners!</i>\n\n{D}"
    )

    all_users  = await get_all_users()
    admin_rows = await get_all_admins()
    admin_ids  = {row["admin_id"] for row in admin_rows}
    if ADMIN_USER_ID: admin_ids.add(ADMIN_USER_ID)
    users_only = [u for u in all_users if u["id"] not in admin_ids]
    sent = failed = 0
    progress = await q.message.reply_text(
        f"📣  Broadcasting to <b>{len(users_only):,}</b> users…",
        parse_mode=ParseMode.HTML)
    for u in users_only:
        try:
            await ctx.bot.send_message(u["id"], broadcast_text, parse_mode=ParseMode.HTML)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.04)
    confirm_msg = (
        f"📣  <b>Contest Results Broadcast Sent</b>\n\n"
        f"🆔  Contest <b>#{cid}</b>\n"
        f"📨  Sent to <b>{sent:,}</b> users  |  ❌ Failed: <b>{failed:,}</b>"
    )
    for aid in admin_ids:
        try: await ctx.bot.send_message(aid, confirm_msg, parse_mode=ParseMode.HTML)
        except Exception: pass
    await progress.edit_text(
        f"✅  <b>Broadcast Complete</b>\n\n"
        f"📨  Sent: <b>{sent:,}</b>  |  ❌ Failed: <b>{failed:,}</b>",
        parse_mode=ParseMode.HTML)
    action_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📣  Share Top 10 to All Users", callback_data=f"ap_share_top10_{cid}")],
        [InlineKeyboardButton("📲  Ask Winners for Fala Number", callback_data=f"ask_fala_{cid}")],
        [InlineKeyboardButton("🔙  Guess Game", callback_data="ap_guessgame")],
    ])
    await q.message.reply_text(
        f"📋  <b>Contest #{cid} — Actions</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=action_kb)


async def handle_admin_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    # ── Forward non-admin messages to any admin watching this user ────────────
    if not await is_admin(uid):
        # ── Fala number reply from a winner ──────────────────────────────────
        if uid in _fala_awaiting:
            info  = _fala_awaiting.pop(uid)
            user  = await get_user(uid)
            uname = f"@{user['username']}" if (user and user.get("username")) else f"<code>{uid}</code>"
            phone = (update.message.text or "").strip()
            fwd_text = (
                f"📲  <b>Winner #{info['rank']} replied!</b>\n\n"
                f"🏆  Contest: <b>{info['question']}</b>\n"
                f"✅  Their pick: <b>{info['guess']}</b>\n"
                f"👤  User: {uname}  <code>({uid})</code>\n"
                f"📞  Phone / Fala ID: <code>{phone}</code>"
            )
            reward_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅  Reward Sent", callback_data=f"reward_sent_{uid}"),
                InlineKeyboardButton("❌  Dismiss",     callback_data="noop"),
            ]])
            for aid in info["admin_ids"]:
                try:
                    await ctx.bot.send_message(
                        aid, fwd_text,
                        parse_mode=ParseMode.HTML, reply_markup=reward_kb)
                except Exception: pass
            await update.message.reply_text(
                "✅  Thank you! Your number has been received. "
                "Your reward will be deposited shortly. 🍀",
                parse_mode=ParseMode.HTML)
            return

        watching = await get_watching_admins(uid)
        if watching:
            user = await get_user(uid)
            uname = f"@{user['username']}" if (user and user.get("username")) else f"<code>{uid}</code>"
            fwd_text = (
                f"💬  <b>Message from {uname}</b>\n"
                f"<code>{uid}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{update.message.text}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            reply_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(f"↩️  Reply to {uname}", callback_data=f"dm_reply_{uid}")
            ]])
            for w in watching:
                try:
                    await ctx.bot.send_message(
                        w["admin_id"], fwd_text,
                        parse_mode=ParseMode.HTML, reply_markup=reply_kb)
                except Exception: pass
        return

    action = ctx.user_data.get("ap_action")

    # ── Admin shortcuts: any of these → Admin Panel ─────────────────────────────
    raw_text   = (update.message.text or "").strip()
    normalized = raw_text.upper().replace("-", "").replace(" ", "").lstrip("/")
    _ADMIN_PANEL_TRIGGERS = {
        "ADMIN", "ADMINPANEL", "ADMINPANAL", "ADMINMENU",
        "MAIN", "MENU", "M", "AP",
    }
    if normalized in _ADMIN_PANEL_TRIGGERS:
        ctx.user_data.pop("ap_action", None)
        ctx.user_data.pop("ap_step",   None)
        ctx.user_data.pop("ap_data",   None)
        await show_ap_main(update.message)
        return

    if not action: return

    text  = (update.message.text or "").strip()
    step  = ctx.user_data.get("ap_step", 1)
    data  = ctx.user_data.get("ap_data", {})
    chat  = update.effective_chat.id
    bot   = ctx.bot

    async def clear():
        ctx.user_data.pop("ap_action", None)
        ctx.user_data.pop("ap_step",   None)
        ctx.user_data.pop("ap_data",   None)

    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Admin Panel", callback_data="ap_main")]])

    # ── find ──────────────────────────────────────────────────────────────────
    if action == "find":
        target = await resolve_target(text)
        if not target:
            await update.message.reply_text("⚠️  User not found. They must have started the bot first.", reply_markup=back_btn)
            await clear(); return
        target_id, label = target
        user   = await get_user(target_id)
        done   = await get_user_completed_task_ids(target_id)
        rank   = await get_user_rank(target_id)
        within, to_next, span = level_info(user["points"], user["level"])
        bar    = progress_bar(within, span, 10)
        joined = user["created_at"].strftime("%d %b %Y %H:%M UTC") if user.get("created_at") else "?"
        banned_flag = "🚫  Yes" if await is_banned(target_id) else "✅  No"
        admin_flag  = "👑  Yes" if await is_admin(target_id) else "—"
        streak = user.get("streak", 0) or 0; refs = user.get("referral_count", 0) or 0
        await update.message.reply_text(
            f"{LOGO}\n{D}\n\n"
            f"👤  <b>User Profile</b>\n\n"
            f"Username: {label}\nID: <code>{user['id']}</code>\n"
            f"Language: {'🇪🇹 Amharic' if user['lang']=='am' else '🇬🇧 English'}\n"
            f"{D2}\n"
            f"{lv_badge(user['level'])}  Level: <b>{user['level']} ({lv_name(user['level'])})</b>\n"
            f"💰  Points: <b>{user['points']:,}</b>  (Rank #{rank})\n"
            f"{bar}\n"
            f"🔥  Streak: <b>{streak} days</b>\n"
            f"🤝  Referrals: <b>{refs}</b>\n"
            f"✅  Tasks Done: <b>{len(done)}</b>\n"
            f"{D2}\n"
            f"🚫  Banned: {banned_flag}\n"
            f"👑  Admin:  {admin_flag}\n"
            f"📅  Joined: {joined}\n\n{D}",
            parse_mode=ParseMode.HTML, reply_markup=back_btn)
        await clear(); return

    # ── ban ───────────────────────────────────────────────────────────────────
    if action == "ban":
        parts  = text.split(maxsplit=1)
        target = await resolve_target(parts[0])
        if not target:
            await update.message.reply_text("⚠️  User not found.", reply_markup=back_btn); await clear(); return
        target_id, label = target
        if await is_admin(target_id):
            await update.message.reply_text("🚫  Cannot ban an admin.", reply_markup=back_btn); await clear(); return
        reason = parts[1] if len(parts) > 1 else "No reason given"
        await ban_user(target_id, uid, reason)
        try:
            await bot.send_message(target_id,
                f"{LOGO}\n{D}\n\n🚫  <b>You have been banned.</b>\nReason: <i>{reason}</i>\n\n{D}",
                parse_mode=ParseMode.HTML)
        except Exception: pass
        await admin_result(bot, chat, "🚫", "User Banned",
            f"User: {label}\nReason: <i>{reason}</i>")
        await clear(); return

    # ── unban ─────────────────────────────────────────────────────────────────
    if action == "unban":
        target = await resolve_target(text)
        if not target:
            await update.message.reply_text("⚠️  User not found.", reply_markup=back_btn); await clear(); return
        target_id, label = target
        await unban_user(target_id)
        try:
            await bot.send_message(target_id,
                f"{LOGO}\n{D}\n\n✅  <b>You have been unbanned!</b>\nSend /start to continue.\n\n{D}",
                parse_mode=ParseMode.HTML)
        except Exception: pass
        await admin_result(bot, chat, "✅", "User Unbanned", f"User: {label}")
        await clear(); return

    # ── give / take / set points ──────────────────────────────────────────────
    if action in ("give", "take", "set"):
        parts = text.split(maxsplit=1)
        target = await resolve_target(parts[0])
        if not target:
            await update.message.reply_text("⚠️  User not found.", reply_markup=back_btn); await clear(); return
        if len(parts) < 2:
            await update.message.reply_text("⚠️  Provide @username and amount.", reply_markup=back_btn); await clear(); return
        try:
            amount = int(parts[1])
        except ValueError:
            await update.message.reply_text("⚠️  Amount must be a number.", reply_markup=back_btn); await clear(); return
        target_id, label = target
        if action == "give":
            leveled_up, new_level = await add_points(target_id, abs(amount))
            result_text = f"User: {label}\nAdded: <b>+{amount:,} pts</b>"
            if leveled_up: result_text += f"\n🎉  They leveled up to Level {new_level}!"
            try:
                await bot.send_message(target_id,
                    f"{LOGO}\n{D}\n\n🎁  <b>Points Gift!</b>\n\nAn admin gifted you  <b>+{amount:,} pts</b>!\n\n{D}",
                    parse_mode=ParseMode.HTML)
            except Exception: pass
            await admin_result(bot, chat, "➕", "Points Given", result_text)
        elif action == "take":
            await add_points(target_id, -abs(amount))
            await admin_result(bot, chat, "➖", "Points Deducted", f"User: {label}\nDeducted: <b>{amount:,} pts</b>")
        else:
            await set_points(target_id, amount)
            await admin_result(bot, chat, "🎯", "Points Set", f"User: {label}\nNew balance: <b>{amount:,} pts</b>")
        await clear(); return

    # ── resetstreak ───────────────────────────────────────────────────────────
    if action == "resetstreak":
        target = await resolve_target(text)
        if not target:
            await update.message.reply_text("⚠️  User not found.", reply_markup=back_btn); await clear(); return
        target_id, label = target
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET streak=0 WHERE id=$1", target_id)
        await admin_result(bot, chat, "🔄", "Streak Reset", f"User: {label}\nStreak set to 0.")
        await clear(); return

    # ── addadmin ──────────────────────────────────────────────────────────────
    if action == "addadmin":
        target = await resolve_target(text)
        if not target:
            await update.message.reply_text("⚠️  User not found. They must have started the bot first.", reply_markup=back_btn)
            await clear(); return
        target_id, label = target
        if await is_admin(target_id):
            await update.message.reply_text(f"⚠️  {label} is already an admin.", parse_mode=ParseMode.HTML, reply_markup=back_btn)
            await clear(); return
        await add_admin(target_id, uid)
        try:
            await bot.send_message(target_id,
                f"{LOGO}\n{D}\n\n👑  <b>You've been promoted to Admin!</b>\n\n"
                f"Send /admin to open your admin panel.\n\n{D}", parse_mode=ParseMode.HTML)
        except Exception: pass
        await admin_result(bot, chat, "👑", "Admin Added", f"User: {label}\nRole: Admin")
        await clear(); return

    # ── removeadmin ───────────────────────────────────────────────────────────
    if action == "removeadmin":
        target = await resolve_target(text)
        if not target:
            await update.message.reply_text("⚠️  User not found.", reply_markup=back_btn); await clear(); return
        target_id, label = target

        # Self-demotion is always allowed
        if target_id == uid:
            if target_id == ADMIN_USER_ID:
                await update.message.reply_text(
                    "ℹ️  You are the primary admin via environment variable.\n"
                    "Your admin access is set in code and cannot be removed from here.",
                    reply_markup=back_btn)
                await clear(); return
            await remove_admin(target_id)
            await admin_result(bot, chat, "✅", "Self-Demoted", f"You removed yourself from admin.")
            await clear(); return

        record = await get_admin_record(target_id)
        if not record:
            await update.message.reply_text(f"⚠️  {label} is not a sub-admin.", parse_mode=ParseMode.HTML, reply_markup=back_btn)
            await clear(); return
        # Super admin can remove anyone; others can only remove who they added
        if uid != ADMIN_USER_ID and record["created_by"] != uid:
            await update.message.reply_text(
                "🚫  You can only remove admins that you personally promoted.",
                reply_markup=back_btn)
            await clear(); return
        await remove_admin(target_id)
        try:
            await bot.send_message(target_id,
                f"{LOGO}\n{D}\n\n📢  <b>Admin Status Updated</b>\n\nYou have been removed as admin.\n\n{D}",
                parse_mode=ParseMode.HTML)
        except Exception: pass
        await admin_result(bot, chat, "➖", "Admin Removed", f"User: {label}")
        await clear(); return

    # ── addtask ───────────────────────────────────────────────────────────────
    if action == "addtask":
        parts = [p.strip() for p in text.split("|")]
        title = parts[0] if parts else ""
        link  = parts[1] if len(parts) > 1 and parts[1] else None
        try:
            pts = int(parts[2]) if len(parts) > 2 and parts[2] else (200 if link else 150)
        except ValueError:
            pts = 200 if link else 150
        if not title:
            await update.message.reply_text("⚠️  Title is required. Format:  Title | link | pts", reply_markup=back_btn)
            await clear(); return
        task = await create_task(title, "", pts, link)
        await admin_result(bot, chat, "✅", "Task Created",
            f"<b>#{task['id']}: {task['title']}</b>\n💰 +{task['points']:,} pts\n"
            + (f"🔗 {link}" if link else "📱 App task"))
        await clear(); return

    # ── addreward ─────────────────────────────────────────────────────────────
    if action == "addreward":
        parts = [p.strip() for p in text.split("|")]
        title = parts[0] if parts else ""
        desc  = parts[1] if len(parts) > 1 else ""
        try:
            cost = int(parts[2]) if len(parts) > 2 and parts[2] else 1000
        except ValueError:
            cost = 1000
        if not title:
            await update.message.reply_text("⚠️  Title is required. Format:  Title | desc | cost", reply_markup=back_btn)
            await clear(); return
        reward = await create_reward(title, desc, cost)
        await admin_result(bot, chat, "✅", "Reward Created",
            f"<b>#{reward['id']}: {reward['title']}</b>\n💰 Cost: {reward['cost']:,} pts")
        await clear(); return

    # ── broadcast ─────────────────────────────────────────────────────────────
    if action == "broadcast":
        users = await get_all_users()
        if not users:
            await update.message.reply_text("📭  No registered users yet."); await clear(); return
        msg = await update.message.reply_text(f"📣  Sending to <b>{len(users):,}</b> users…", parse_mode=ParseMode.HTML)
        sent = failed = 0
        for u in users:
            try:
                await bot.send_message(u["id"],
                    f"{LOGO}\n{D}\n\n📣  <b>Message from Admin</b>\n\n{text}\n\n{D}",
                    parse_mode=ParseMode.HTML)
                sent += 1
            except Exception: failed += 1
            await asyncio.sleep(0.04)
        await msg.edit_text(
            f"✅  <b>Broadcast Complete</b>\n\n📨 Sent: <b>{sent:,}</b>  ❌ Failed: <b>{failed:,}</b>",
            parse_mode=ParseMode.HTML)
        await clear(); return

    # ── announce ──────────────────────────────────────────────────────────────
    if action == "announce":
        users = await get_all_users()
        if not users:
            await update.message.reply_text("📭  No registered users yet."); await clear(); return
        msg = await update.message.reply_text(f"📢  Sending announcement to <b>{len(users):,}</b> users…", parse_mode=ParseMode.HTML)
        now  = datetime.now(timezone.utc).strftime("%d %b %Y • %H:%M UTC")
        sent = failed = 0
        for u in users:
            try:
                await bot.send_message(u["id"],
                    f"{LOGO}\n{D}\n\n📢  <b>📣 ANNOUNCEMENT</b>\n\n{text}\n\n{D2}\n<i>🕐 {now}</i>\n{D}",
                    parse_mode=ParseMode.HTML)
                sent += 1
            except Exception: failed += 1
            await asyncio.sleep(0.04)
        await msg.edit_text(
            f"✅  <b>Announcement Sent</b>\n\n📨 Sent: <b>{sent:,}</b>  ❌ Failed: <b>{failed:,}</b>",
            parse_mode=ParseMode.HTML)
        await clear(); return

    # ── draw ──────────────────────────────────────────────────────────────────
    if action == "draw":
        parts = text.split()
        try:
            prize_pts = int(parts[0])
        except (ValueError, IndexError):
            await update.message.reply_text("⚠️  Enter prize amount (and optional min_pts).", reply_markup=back_btn)
            await clear(); return
        try:
            min_pts = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            min_pts = 0
        users = await get_all_users_full()
        eligible = [u for u in users if u["points"] >= min_pts]
        if not eligible:
            await update.message.reply_text(f"⚠️  No eligible users with ≥ {min_pts:,} pts.", reply_markup=back_btn)
            await clear(); return
        msg = await update.message.reply_text(
            f"🍀  <b>Drawing winner…</b>\n\nPool: <b>{len(eligible)}</b> users\nPrize: <b>{prize_pts:,} pts</b>",
            parse_mode=ParseMode.HTML)
        await asyncio.sleep(1.5)
        winner = random.choice(eligible)
        wname  = f"@{winner['username']}" if winner["username"] else f"<code>{winner['id']}</code>"
        leveled_up, new_level = await add_points(winner["id"], prize_pts)
        await log_draw(winner["id"], prize_pts, uid)
        await msg.edit_text(
            f"{LOGO}\n{D}\n\n"
            f"🎉  <b>LOTTERY WINNER!</b>\n\n"
            f"🏆  Winner: {wname}\n"
            f"💰  Prize:  <b>+{prize_pts:,} pts</b>\n"
            f"👥  Pool: <b>{len(eligible)}</b> users\n"
            + (f"🌟  Leveled up to Level {new_level}!\n" if leveled_up else "")
            + f"\n{D}",
            parse_mode=ParseMode.HTML)
        try:
            await bot.send_message(winner["id"],
                f"{LOGO}\n{D}\n\n🎉  <b>YOU WON THE LOTTERY!</b>\n\n"
                f"You were selected as the winner! 🏆\n"
                f"💰  Prize: <b>+{prize_pts:,} pts</b> added!\n\n{D}",
                parse_mode=ParseMode.HTML)
        except Exception: pass
        await clear(); return

    # ── watch ─────────────────────────────────────────────────────────────────
    if action == "watch":
        target = await resolve_target(text)
        if not target:
            await update.message.reply_text("⚠️  User not found. They must have started the bot first.", reply_markup=back_btn)
            await clear(); return
        target_id, label = target
        if await is_admin(target_id):
            await update.message.reply_text("⚠️  Cannot watch another admin.", reply_markup=back_btn)
            await clear(); return
        await watch_user(uid, target_id)
        await admin_result(bot, chat, "🔔", "Watch Enabled",
            f"Now watching: <b>{label}</b>\n\nEvery message they send to the bot will be forwarded to you with a Reply button.")
        await clear(); return

    # ── unwatch ───────────────────────────────────────────────────────────────
    if action == "unwatch":
        target = await resolve_target(text)
        if not target:
            await update.message.reply_text("⚠️  User not found.", reply_markup=back_btn)
            await clear(); return
        target_id, label = target
        await unwatch_user(uid, target_id)
        await admin_result(bot, chat, "🔕", "Watch Disabled",
            f"Stopped watching: <b>{label}</b>")
        await clear(); return

    # ── dm (2-step: username → message) ───────────────────────────────────────
    if action == "dm":
        if step == 1:
            target = await resolve_target(text)
            if not target:
                await update.message.reply_text("⚠️  User not found.", reply_markup=back_btn)
                await clear(); return
            target_id, label = target
            ctx.user_data["ap_step"] = 2
            ctx.user_data["ap_data"] = {"target_id": target_id, "label": label}
            await admin_prompt(bot, chat,
                f"DM a User — Step 2",
                f"Now type your message for <b>{label}</b>.\n\n"
                f"Supports HTML: <b>bold</b>, <i>italic</i>, <code>code</code>.",
                "Your message here…")
            return
        elif step == 2:
            target_id = data.get("target_id")
            label     = data.get("label", "user")
            try:
                await bot.send_message(target_id, text, parse_mode=ParseMode.HTML)
                await admin_result(bot, chat, "📨", "Message Delivered",
                    f"To: <b>{label}</b>\n\nPreview: <i>{text[:120]}</i>")
            except Exception as e:
                await update.message.reply_text(f"⚠️  Could not deliver message: {e}", reply_markup=back_btn)
            await clear(); return

    # ── dm_reply (reply to a forwarded user message) ──────────────────────────
    if action == "dm_reply":
        target_id = data.get("target_id")
        label     = data.get("label", "user")
        try:
            await bot.send_message(target_id, text, parse_mode=ParseMode.HTML)
            await admin_result(bot, chat, "↩️", "Reply Sent",
                f"To: <b>{label}</b>\n\nPreview: <i>{text[:120]}</i>")
        except Exception as e:
            await update.message.reply_text(f"⚠️  Could not deliver reply: {e}", reply_markup=back_btn)
        await clear(); return

    # ── newscore (3-step: team1 → team2 → deadline) ───────────────────────────
    if action == "newscore":
        if step == 1:
            if not text:
                await update.message.reply_text("⚠️  Team 1 name cannot be empty.", reply_markup=back_btn)
                await clear(); return
            ctx.user_data["ap_step"] = 2
            ctx.user_data["ap_data"] = {"team1": text, "contest_type": "score"}
            await admin_prompt(bot, chat,
                "New Score Contest — Step 2",
                f"✅  Team 1: <b>{text}</b>\n\n"
                f"Now enter the name of <b>Team 2</b>.\n\n"
                f"This is the second team (right side of the score).",
                "Morocco")
            return
        elif step == 2:
            if not text:
                await update.message.reply_text("⚠️  Team 2 name cannot be empty.", reply_markup=back_btn)
                await clear(); return
            ctx.user_data["ap_step"] = 3
            ctx.user_data["ap_data"]["team2"] = text
            t1 = data.get("team1", "")
            await admin_prompt(bot, chat,
                "New Score Contest — Step 3",
                f"✅  <b>{t1}</b>  vs  <b>{text}</b>\n\n"
                f"Finally, enter the <b>deadline</b> in hours.\n\n"
                f"Examples: <code>3</code> = 3 hrs  •  <code>0.5</code> = 30 min  •  <code>24</code> = 1 day",
                "3")
            return
        elif step == 3:
            try:
                hours = float(text.replace(",", "."))
                if hours <= 0: raise ValueError
            except ValueError:
                await update.message.reply_text(
                    "⚠️  Enter a positive number of hours (e.g. <code>3</code> or <code>0.5</code>).",
                    parse_mode=ParseMode.HTML, reply_markup=back_btn)
                await clear(); return
            team1    = data.get("team1", "Team 1")
            team2    = data.get("team2", "Team 2")
            question = f"{team1} vs {team2}"
            contest  = await create_contest(uid, question, "score", hours, team1, team2)
            cid      = contest["id"]
            dl_str   = contest["deadline"].strftime("%d %b %Y %H:%M UTC")
            all_users  = await get_all_users()
            admin_rows = await get_all_admins()
            admin_ids  = {row["admin_id"] for row in admin_rows}
            if ADMIN_USER_ID: admin_ids.add(ADMIN_USER_ID)
            body = (
                f"{LOGO}\n{D}\n\n"
                f"⚽  <b>Score Prediction Contest!</b>\n\n"
                f"🔵  <b>{team1}</b>  vs  🔴  <b>{team2}</b>\n\n"
                f"⏰  Deadline: <b>{dl_str}</b>\n\n"
                f"🎯  Predict the final score using the number pad!\n\n"
                f"{D}"
            )
            user_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🏆  Participate", callback_data=f"guess_participate_{cid}"),
            ]])
            sent = 0; failed = 0
            for u in all_users:
                if u["id"] in admin_ids: continue   # skip admins
                try:
                    await bot.send_message(u["id"], body, parse_mode=ParseMode.HTML, reply_markup=user_kb)
                    sent += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(0.04)
            confirm_msg = (
                f"📣  <b>Contest Broadcast Sent</b>\n\n"
                f"⚽  <b>{question}</b>\n"
                f"🆔  Contest <b>#{cid}</b>  •  Deadline: <b>{dl_str}</b>\n"
                f"📨  Sent to <b>{sent:,}</b> users  |  ❌ Failed: <b>{failed}</b>"
            )
            for aid in admin_ids:
                try: await bot.send_message(aid, confirm_msg, parse_mode=ParseMode.HTML)
                except Exception: pass
            await admin_result(bot, chat, "⚽", "Score Contest Created & Broadcast",
                f"ID: <b>#{cid}</b>\n"
                f"Match: <b>{question}</b>\n"
                f"Deadline: <b>{dl_str}</b>\n"
                f"Sent: <b>{sent:,}</b>  |  Failed: <b>{failed}</b>")
            await clear(); return

    # ── newresult (2-step: title → deadline) ──────────────────────────────────
    if action == "newresult":
        contest_type = "result"
        if step == 1:
            ctx.user_data["ap_step"] = 2
            ctx.user_data["ap_data"] = {"question": text, "contest_type": contest_type}
            await admin_prompt(bot, chat,
                "Result Contest — Step 2",
                "Enter the deadline in <b>hours</b>.\n\n"
                "Examples: <code>3</code> = 3 hours,  <code>0.5</code> = 30 minutes,  <code>24</code> = 1 day",
                "3")
            return
        elif step == 2:
            try:
                hours = float(text.replace(",", "."))
                if hours <= 0: raise ValueError
            except ValueError:
                await update.message.reply_text(
                    "⚠️  Enter a positive number of hours (e.g. <code>3</code> or <code>0.5</code>).",
                    parse_mode=ParseMode.HTML, reply_markup=back_btn)
                await clear(); return
            question   = data.get("question", "")
            contest    = await create_contest(uid, question, "result", hours)
            cid        = contest["id"]
            dl_str     = contest["deadline"].strftime("%d %b %Y %H:%M UTC")
            all_users  = await get_all_users()
            admin_rows = await get_all_admins()
            admin_ids  = {row["admin_id"] for row in admin_rows}
            if ADMIN_USER_ID: admin_ids.add(ADMIN_USER_ID)
            body = (
                f"{LOGO}\n{D}\n\n"
                f"🎯  <b>New Result Poll!</b>\n\n"
                f"<b>{question}</b>\n\n"
                f"⏰  Deadline: <b>{dl_str}</b>\n\n"
                f"{D}"
            )
            user_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("1️⃣  Win 1", callback_data=f"guess_result_{cid}_win1"),
                InlineKeyboardButton("🤝  Draw",   callback_data=f"guess_result_{cid}_draw"),
                InlineKeyboardButton("2️⃣  Win 2", callback_data=f"guess_result_{cid}_win2"),
            ]])
            sent = 0; failed = 0
            for u in all_users:
                if u["id"] in admin_ids: continue   # skip admins
                try:
                    await bot.send_message(u["id"], body, parse_mode=ParseMode.HTML, reply_markup=user_kb)
                    sent += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(0.04)
            confirm_msg = (
                f"📣  <b>Contest Broadcast Sent</b>\n\n"
                f"🎯  <b>{question}</b>\n"
                f"🆔  Contest <b>#{cid}</b>  •  Deadline: <b>{dl_str}</b>\n"
                f"📨  Sent to <b>{sent:,}</b> users  |  ❌ Failed: <b>{failed}</b>"
            )
            for aid in admin_ids:
                try: await bot.send_message(aid, confirm_msg, parse_mode=ParseMode.HTML)
                except Exception: pass
            await admin_result(bot, chat, "🎯", "Result Contest Created & Broadcast",
                f"ID: <b>#{cid}</b>\n"
                f"Type: <b>Win / Draw / Win2</b>\n"
                f"Deadline: <b>{dl_str}</b>\n"
                f"Sent: <b>{sent:,}</b>  |  Failed: <b>{failed}</b>")
            await clear(); return

    # ── resolve (contest_id → dial-pad or result buttons) ────────────────────
    if action == "resolve":
        if step == 1:
            try:
                cid = int(text.strip())
            except ValueError:
                await update.message.reply_text("⚠️  Enter a valid numeric contest ID.", reply_markup=back_btn)
                await clear(); return
            contest = await get_contest(cid)
            if not contest:
                await update.message.reply_text(f"⚠️  Contest #{cid} not found.", reply_markup=back_btn)
                await clear(); return
            entries = await get_contest_entry_count(cid)
            await clear()
            if contest["contest_type"] == "score":
                team1 = contest.get("team1") or "Team 1"
                team2 = contest.get("team2") or "Team 2"
                kb = _admin_score_kb("resolve_t1", cid)
                await bot.send_message(
                    chat,
                    f"{LOGO}\n{D}\n\n"
                    f"✅  <b>Resolve Contest #{cid}</b>\n\n"
                    f"📝  <b>{contest['question']}</b>\n"
                    f"👥  Entries: <b>{entries:,}</b>\n\n"
                    f"Tap the correct goals for  <b>{team1}</b>:\n\n{D}",
                    parse_mode=ParseMode.HTML, reply_markup=kb)
            else:
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("1️⃣  Win 1", callback_data=f"resolve_result_{cid}_win1"),
                    InlineKeyboardButton("🤝  Draw",   callback_data=f"resolve_result_{cid}_draw"),
                    InlineKeyboardButton("2️⃣  Win 2", callback_data=f"resolve_result_{cid}_win2"),
                ]])
                await bot.send_message(
                    chat,
                    f"{LOGO}\n{D}\n\n"
                    f"✅  <b>Resolve Contest #{cid}</b>\n\n"
                    f"📝  <b>{contest['question']}</b>\n"
                    f"👥  Entries: <b>{entries:,}</b>\n\n"
                    f"What was the actual result?\n\n{D}",
                    parse_mode=ParseMode.HTML, reply_markup=kb)
            return

    # ── topguess (1-step: contest_id → show top 10 + purge) ──────────────────
    if action == "topguess":
        if step == 1:
            try:
                cid = int(text.strip())
            except ValueError:
                await update.message.reply_text("⚠️  Enter a valid numeric contest ID.", reply_markup=back_btn)
                await clear(); return
            contest = await get_contest(cid)
            if not contest:
                await update.message.reply_text(f"⚠️  Contest #{cid} not found.", reply_markup=back_btn)
                await clear(); return
            winners = await get_correct_guessers(cid, 10)
            if not winners:
                await update.message.reply_text(
                    f"⚠️  No correct guessers found for contest #{cid}.\n\n"
                    f"Resolve the contest first (✅ Resolve Contest).",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back", callback_data="ap_guessgame")]]))
                await clear(); return
            await purge_losers(cid, 10)
            lines = []
            for i, w in enumerate(winners):
                uname = f"@{w['username']}" if w.get("username") else f"<code>{w['user_id']}</code>"
                t_str = w["submitted_at"].strftime("%H:%M:%S") if w.get("submitted_at") else "?"
                medal = RANK_MEDALS[i] if i < len(RANK_MEDALS) else f"#{i+1}"
                lines.append(f"{medal}  {uname} — <b>{w['guess']}</b>  <i>at {t_str}</i>")
            await update.message.reply_text(
                f"{LOGO}\n{D}\n\n"
                f"🏆  <b>Top {len(winners)} Correct Guessers</b>\n"
                f"📋  Contest #{cid}: <b>{contest['question']}</b>\n"
                f"✅  Answer: <b>{contest.get('correct_answer', '—')}</b>\n\n"
                + "\n".join(lines) + "\n\n"
                f"{D2}\n🗑  <i>Incorrect entries cleared. Only winners remain.</i>\n\n{D}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙  Back", callback_data="ap_guessgame")]]))
            await clear(); return


# ══════════════════════════════════════════════════════════════════════════════
#  DB init
# ══════════════════════════════════════════════════════════════════════════════

async def init_db():
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY, username TEXT, lang TEXT DEFAULT 'en',
                points INTEGER DEFAULT 0, level INTEGER DEFAULT 1,
                streak INTEGER DEFAULT 0, referral_count INTEGER DEFAULT 0,
                referred_by BIGINT, daily_claimed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW())""")
        for col, defn in [("streak","INTEGER DEFAULT 0"),("referral_count","INTEGER DEFAULT 0"),("referred_by","BIGINT")]:
            await conn.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {defn}")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY, role TEXT DEFAULT 'admin',
                created_by BIGINT, created_at TIMESTAMPTZ DEFAULT NOW())""")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id BIGINT PRIMARY KEY, banned_by BIGINT,
                reason TEXT DEFAULT '', created_at TIMESTAMPTZ DEFAULT NOW())""")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT DEFAULT '',
                points INTEGER DEFAULT 100, link TEXT, active BOOLEAN DEFAULT true,
                created_at TIMESTAMPTZ DEFAULT NOW())""")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS task_completions (
                user_id BIGINT NOT NULL, task_id INTEGER NOT NULL,
                completed_at TIMESTAMPTZ DEFAULT NOW(), PRIMARY KEY (user_id, task_id))""")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS rewards (
                id SERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT DEFAULT '',
                cost INTEGER DEFAULT 1000, active BOOLEAN DEFAULT true,
                created_at TIMESTAMPTZ DEFAULT NOW())""")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS draw_history (
                id SERIAL PRIMARY KEY, winner_id BIGINT NOT NULL, prize_pts INTEGER NOT NULL,
                run_by BIGINT, notes TEXT DEFAULT '', created_at TIMESTAMPTZ DEFAULT NOW())""")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS direct_chats (
                admin_id BIGINT NOT NULL, target_user_id BIGINT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (admin_id, target_user_id))""")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS guess_contests (
                id SERIAL PRIMARY KEY,
                admin_id BIGINT NOT NULL,
                question TEXT NOT NULL,
                contest_type TEXT DEFAULT 'score',
                deadline TIMESTAMPTZ,
                correct_answer TEXT,
                status TEXT DEFAULT 'open',
                team1 TEXT DEFAULT '',
                team2 TEXT DEFAULT '',
                created_at TIMESTAMPTZ DEFAULT NOW())""")
        for col, defn in [("team1","TEXT DEFAULT ''"),("team2","TEXT DEFAULT ''")]:
            await conn.execute(f"ALTER TABLE guess_contests ADD COLUMN IF NOT EXISTS {col} {defn}")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS guess_entries (
                contest_id INTEGER NOT NULL,
                user_id BIGINT NOT NULL,
                guess TEXT NOT NULL,
                is_correct BOOLEAN DEFAULT FALSE,
                submitted_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (contest_id, user_id))""")
    print("✅ Tables initialized")


async def post_init(app: Application):
    global pool, MAINTENANCE_MODE
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    await init_db()
    await seed_tasks()
    MAINTENANCE_MODE = await get_setting("maintenance", "0") == "1"
    print(f"✅ Ready | maintenance={'ON' if MAINTENANCE_MODE else 'OFF'}")


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # User onboarding
    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CallbackQueryHandler(cb_lang,        pattern=r"^lang_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_age_yes,     pattern=r"^age_yes_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_age_no,      pattern=r"^age_no_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_tos_yes,     pattern=r"^tos_yes_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_tos_no,      pattern=r"^tos_no_(en|am)$"))

    # User menu
    app.add_handler(CallbackQueryHandler(cb_menu_back,     pattern=r"^menu_back_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_menu_points,   pattern=r"^menu_points_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_menu_tasks,    pattern=r"^menu_tasks_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_menu_rewards,  pattern=r"^menu_rewards_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_menu_lb,       pattern=r"^menu_lb_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_menu_referral, pattern=r"^menu_referral_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_menu_ads,      pattern=r"^menu_ads_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_menu_settings, pattern=r"^menu_settings_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_switch_lang,   pattern=r"^switch_lang_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_daily,         pattern=r"^daily_(en|am)$"))

    # Tasks
    app.add_handler(CallbackQueryHandler(cb_tasks_page,    pattern=r"^tasks_page_\d+_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_task_noop,     pattern=r"^task_noop_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_task_already,  pattern=r"^task_already_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_task_claim,    pattern=r"^task_claim_\d+_(en|am)$"))

    # Admin panel navigation
    app.add_handler(CommandHandler("admin",             cmd_admin))
    app.add_handler(CommandHandler("menu",              cmd_menu))
    app.add_handler(CallbackQueryHandler(cb_ap_main,         pattern=r"^ap_main$"))
    app.add_handler(CallbackQueryHandler(cb_ap_users,        pattern=r"^ap_users$"))
    app.add_handler(CallbackQueryHandler(cb_ap_admins,       pattern=r"^ap_admins$"))
    app.add_handler(CallbackQueryHandler(cb_ap_tasks,        pattern=r"^ap_tasks$"))
    app.add_handler(CallbackQueryHandler(cb_ap_rewards,      pattern=r"^ap_rewards$"))
    app.add_handler(CallbackQueryHandler(cb_ap_stats,        pattern=r"^ap_stats$"))
    app.add_handler(CallbackQueryHandler(cb_ap_lottery,      pattern=r"^ap_lottery$"))
    app.add_handler(CallbackQueryHandler(cb_ap_broadcast,    pattern=r"^ap_broadcast$"))
    app.add_handler(CallbackQueryHandler(cb_ap_system,       pattern=r"^ap_system$"))
    app.add_handler(CallbackQueryHandler(cb_ap_directchat,   pattern=r"^ap_directchat$"))
    app.add_handler(CallbackQueryHandler(cb_dm_reply_btn,    pattern=r"^dm_reply_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_ap_guessgame,    pattern=r"^ap_guessgame$"))
    # Guess Game user callbacks — score dial-pad
    app.add_handler(CallbackQueryHandler(cb_guess_participate, pattern=r"^guess_participate_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_score_t1,          pattern=r"^score_t1_\d+_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_score_t2,          pattern=r"^score_t2_\d+_\d+_\d+$"))
    # Guess Game user callbacks — result poll
    app.add_handler(CallbackQueryHandler(cb_guess_result,    pattern=r"^guess_result_\d+_(win1|draw|win2)$"))
    # Guess Game admin callbacks
    app.add_handler(CallbackQueryHandler(cb_stop_contest,    pattern=r"^stop_contest_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_resolve_t1,      pattern=r"^resolve_t1_\d+_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_resolve_t2,      pattern=r"^resolve_t2_\d+_\d+_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_resolve_result,  pattern=r"^resolve_result_\d+_(win1|draw|win2)$"))
    app.add_handler(CallbackQueryHandler(cb_ap_showtop,       pattern=r"^ap_showtop_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_ap_share_top10,  pattern=r"^ap_share_top10_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_ask_fala_number, pattern=r"^ask_fala_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_reward_sent,     pattern=r"^reward_sent_\d+$"))
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern=r"^noop$"))

    # Admin actions
    app.add_handler(CallbackQueryHandler(cb_ap_act,          pattern=r"^ap_act_"))
    app.add_handler(CallbackQueryHandler(cb_ap_del_task,     pattern=r"^ap_del_task_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_ap_confirm_deltask, pattern=r"^ap_confirm_deltask_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_ap_del_reward,   pattern=r"^ap_del_reward_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_ap_confirm_delreward, pattern=r"^ap_confirm_delreward_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_adm_task_toggle, pattern=r"^adm_task_toggle_\d+_(on|off)$"))
    app.add_handler(CallbackQueryHandler(cb_adm_reward_toggle, pattern=r"^adm_reward_toggle_\d+_(on|off)$"))

    # Catch admin ForceReply inputs (must be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_input))

    print("🤖 Falah.bet bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
