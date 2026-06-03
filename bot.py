import asyncio
import os
from datetime import datetime, timedelta, timezone

import asyncpg
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
DATABASE_URL: str = os.environ["DATABASE_URL"]
ADMIN_USER_ID: int = int(os.environ.get("ADMIN_USER_ID", "0"))

APP_URL = "https://Falah.bet"
TOS_URL = "https://www.notion.so/Terms-Responsible-Use-Policy-372c498a31788008a9bfc60271fb3ef3?source=copy_link"

pool: asyncpg.Pool = None  # type: ignore

# ── Messages ──────────────────────────────────────────────────────────────────

MSG = {
    "en": {
        "lang_button": "🇬🇧 English",
        "language_prompt": "🌐 Please select your language:",
        "age_text": (
            "🎲 Welcome\n\nThis bot provides access to a third-party online gaming service.\n\n"
            "⚠️ Important:\n• 18+ only\n• This service involves real-money risk-based games\n"
            "• You may lose funds\n• Please use responsibly\n\n"
            "This bot is only a navigation tool and is not responsible for external platform activity.\n\n"
            "Confirm your age to continue:"
        ),
        "age_continue": "Confirm ✅",
        "age_exit": "Exit ❌",
        "tos_text": (
            '📋 Terms & Responsible Use Policy\n\nBefore continuing, please read our Terms of Service carefully.\n\n'
            'By tapping "I have read, Continue" you confirm that you have read and agree to the terms.'
        ),
        "tos_read": "📄 Read Terms of Service",
        "tos_continue": "Confirm ✅",
        "tos_exit": "Exit ❌",
        "welcome_final": "✅ All set! Choose an option below:",
        "exit_message": "👋 You have exited. Send /start to begin again.",
        "menu_title": "🏠 Main Menu",
        "btn_profile": "👤 Profile",
        "btn_points": "💰 Points",
        "btn_tasks": "📋 Tasks",
        "btn_rewards": "🎁 Rewards",
        "btn_leaderboard": "🏆 Leaderboard",
        "btn_ads": "📺 Ads (Coming Soon)",
        "btn_settings": "⚙️ Settings",
        "btn_open_app": "🚀 Open App",
        "btn_back": "🔙 Back",
        "btn_daily": "🎁 Claim Daily Reward",
        "daily_already": "⏳ You already claimed today's reward. Come back tomorrow!",
        "no_tasks": "📭 No tasks available right now.",
        "task_already": "⚠️ You already completed this task.",
        "no_rewards": "📭 No rewards available right now.",
        "rewards_title": "🎁 *Rewards*\n\nSpend your points on rewards:",
        "lb_public_title": "🏆 *Leaderboard — Top 3*",
        "settings_title": "⚙️ *Settings*",
        "btn_change_lang": "🌐 Change Language",
        "not_authorized": "🚫 You are not authorized to use this command.",
        "admin_already_exists": "⚠️ That user is already an admin.",
        "admin_not_found": "⚠️ Admin not found.",
        "admin_is_primary": "🚫 Cannot remove the primary admin.",
        "admin_not_yours": "🚫 You can only remove admins you added.",
    },
    "am": {
        "lang_button": "🇪🇹 አማርኛ",
        "language_prompt": "🌐 ቋንቋ ይምረጡ:",
        "age_text": (
            "🎲 እንኳን ደህና መጡ\n\nይህ ቦት የሦስተኛ ወገን የኦንላይን ጨዋታ አገልግሎት ያቀርባል።\n\n"
            "⚠️ አስፈላጊ:\n• ዕድሜ 18+ ብቻ\n• ይህ አገልግሎት ገንዘብን የሚያካትት ጨዋታዎችን ያቀርባል\n"
            "• ገንዘብ ሊያጡ ይችላሉ\n• ኃላፊነት ይሰማዎ\n\n"
            "ይህ ቦት የናቪጌሽን መሳሪያ ብቻ ሲሆን ለውጫዊ መድረክ ተግባር ኃላፊ አይደለም።\n\n"
            "ለመቀጠል ዕድሜዎን ያረጋግጡ:"
        ),
        "age_continue": "አረጋግጣለሁ ✅",
        "age_exit": "ውጣ ❌",
        "tos_text": (
            '📋 የአጠቃቀም ውሎች እና ፖሊሲ\n\nከመቀጠልዎ በፊት፣ የአገልግሎት ሁኔታዎቻችንን በጥንቃቄ ያንብቡ።\n\n'
            '"አንብቤያለሁ፣ ቀጥሉ" ሲጫኑ ውሎቹን አንብበው ተስማምተዋል ማለት ነው።'
        ),
        "tos_read": "📄 ውሎቹን ያንብቡ",
        "tos_continue": "አረጋግጣለሁ ✅",
        "tos_exit": "ውጣ ❌",
        "welcome_final": "✅ ሁሉም ተዘጋጅቷል! ከታች ይምረጡ:",
        "exit_message": "👋 ወጥተዋል። እንደገና ለመጀመር /start ይላኩ።",
        "menu_title": "🏠 ዋና ምናሌ",
        "btn_profile": "👤 መገለጫ",
        "btn_points": "💰 ነጥቦች",
        "btn_tasks": "📋 ተግባራት",
        "btn_rewards": "🎁 ሽልማቶች",
        "btn_leaderboard": "🏆 ሊደርቦርድ",
        "btn_ads": "📺 ማስታወቂያ (በቅርቡ)",
        "btn_settings": "⚙️ ቅንብሮች",
        "btn_open_app": "🚀 መተግበሪያ ክፈት",
        "btn_back": "🔙 ተመለስ",
        "btn_daily": "🎁 የዕለቱ ሽልማት ውሰዱ",
        "daily_already": "⏳ ዛሬ ቀደም ወስደዋል። ነገ ተመለሱ!",
        "no_tasks": "📭 አሁን ምንም ተግባር የለም።",
        "task_already": "⚠️ ይህን ተግባር ቀደም ጨርሰዋታል።",
        "no_rewards": "📭 አሁን ምንም ሽልማት የለም።",
        "rewards_title": "🎁 *ሽልማቶች*\n\nነጥቦችዎን ለሽልማት ይጠቀሙ:",
        "lb_public_title": "🏆 *ሊደርቦርድ — ምርጥ 3*",
        "settings_title": "⚙️ *ቅንብሮች*",
        "btn_change_lang": "🌐 ቋንቋ ቀይር",
        "not_authorized": "🚫 ይህን ትዕዛዝ ለመጠቀም ፈቃድ የለዎትም።",
        "admin_already_exists": "⚠️ ይህ ተጠቃሚ አስቀድሞ አስተዳዳሪ ነው።",
        "admin_not_found": "⚠️ አስተዳዳሪ አልተገኘም።",
        "admin_is_primary": "🚫 ዋና አስተዳዳሪን ማስወገድ አይቻልም።",
        "admin_not_yours": "🚫 የራስዎ ያከሏቸውን አስተዳዳሪዎች ብቻ ማስወገድ ይችላሉ።",
    },
}


def lc(lang: str) -> dict:
    return MSG.get(lang, MSG["en"])


def lang_from(data: str) -> str:
    return "am" if ("_am_" in data or data.endswith("_am")) else "en"


# ── DB helpers ────────────────────────────────────────────────────────────────


async def get_or_create_user(uid: int, username: str | None, lang: str = "en"):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (id, username, lang) VALUES ($1, $2, $3) ON CONFLICT (id) DO NOTHING",
            uid, username, lang,
        )
        return await conn.fetchrow("SELECT * FROM users WHERE id = $1", uid)


async def get_user(uid: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE id = $1", uid)


async def get_user_by_username(username: str):
    clean = username.lstrip("@").lower()
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE lower(username) = $1", clean)


async def set_user_lang(uid: int, lang: str):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET lang = $1 WHERE id = $2", lang, uid)


async def add_points(uid: int, pts: int):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET points = points + $1 WHERE id = $2", pts, uid)
        user = await conn.fetchrow("SELECT points, level FROM users WHERE id = $1", uid)
        if user:
            new_level = user["points"] // 1000 + 1
            if new_level != user["level"]:
                await conn.execute("UPDATE users SET level = $1 WHERE id = $2", new_level, uid)


async def claim_daily(uid: int) -> dict:
    user = await get_user(uid)
    if not user:
        return {"ok": False, "pts": 0}
    now = datetime.now(timezone.utc)
    if user["daily_claimed_at"]:
        last = user["daily_claimed_at"]
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (now - last) < timedelta(hours=24):
            return {"ok": False, "pts": 0}
    pts = 50 + user["level"] * 10
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET daily_claimed_at = $1 WHERE id = $2", now, uid)
    await add_points(uid, pts)
    return {"ok": True, "pts": pts}


async def get_leaderboard(limit: int):
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM users ORDER BY points DESC LIMIT $1", limit)


async def get_user_rank(uid: int) -> int:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM users ORDER BY points DESC")
        for i, row in enumerate(rows):
            if row["id"] == uid:
                return i + 1
        return 0


async def is_admin(uid: int) -> bool:
    if uid == ADMIN_USER_ID:
        return True
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM admins WHERE user_id = $1", uid)
        return row is not None


async def get_admin_record(uid: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM admins WHERE user_id = $1", uid)


async def add_admin(uid: int, created_by: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admins (user_id, role, created_by) VALUES ($1, 'admin', $2) ON CONFLICT DO NOTHING",
            uid, created_by,
        )


async def remove_admin(uid: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM admins WHERE user_id = $1", uid)


async def get_all_users():
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT id FROM users")


async def get_active_tasks():
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM tasks WHERE active = true ORDER BY id")


async def get_all_tasks():
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM tasks ORDER BY id")


async def create_task(title: str, description: str, points: int, link: str | None = None):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "INSERT INTO tasks (title, description, points, link) VALUES ($1, $2, $3, $4) RETURNING *",
            title, description, points, link,
        )


async def toggle_task(task_id: int, active: bool):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE tasks SET active = $1 WHERE id = $2", active, task_id)


async def has_completed_task(uid: int, task_id: int) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM task_completions WHERE user_id = $1 AND task_id = $2", uid, task_id
        )
        return row is not None


async def complete_task(uid: int, task_id: int, pts: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO task_completions (user_id, task_id) VALUES ($1, $2)",
            uid, task_id,
        )
    await add_points(uid, pts)


async def get_user_completed_task_ids(uid: int) -> list[int]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT task_id FROM task_completions WHERE user_id = $1", uid)
        return [r["task_id"] for r in rows]


async def get_active_rewards():
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM rewards WHERE active = true ORDER BY id")


async def create_reward(title: str, description: str, cost: int):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "INSERT INTO rewards (title, description, cost) VALUES ($1, $2, $3) RETURNING *",
            title, description, cost,
        )


async def seed_tasks():
    tasks = await get_active_tasks()
    if tasks:
        return
    await create_task("Join our Official Channel", "Subscribe to stay updated", 200, "https://t.me/falahbetofficial")
    await create_task("Open the App", "Launch Falah.bet and explore", 150)


# ── Keyboard helpers ──────────────────────────────────────────────────────────


def menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    t = lc(lang)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t["btn_profile"], callback_data=f"menu_profile_{lang}"),
         InlineKeyboardButton(t["btn_points"], callback_data=f"menu_points_{lang}")],
        [InlineKeyboardButton(t["btn_tasks"], callback_data=f"menu_tasks_{lang}"),
         InlineKeyboardButton(t["btn_rewards"], callback_data=f"menu_rewards_{lang}")],
        [InlineKeyboardButton(t["btn_leaderboard"], callback_data=f"menu_lb_{lang}")],
        [InlineKeyboardButton(t["btn_ads"], callback_data=f"menu_ads_{lang}")],
        [InlineKeyboardButton(t["btn_settings"], callback_data=f"menu_settings_{lang}")],
        [InlineKeyboardButton(t["btn_open_app"], web_app=WebAppInfo(url=APP_URL))],
    ])


def back_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(lc(lang)["btn_back"], callback_data=f"menu_back_{lang}")]])


# ── /start ────────────────────────────────────────────────────────────────────


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = await get_user(uid)

    # If user already exists → go straight to menu
    if user:
        lang = user["lang"] or "en"
        name = update.effective_user.first_name or "there"

        text = (
    f"🏠 {lc(lang)['menu_title']}\n\n"
    f"👋 Welcome back, {name}"
)

if user["username"]:
    text += f" (@{user['username']})"

text += (
    f"\n⭐ Level: {user['level']}\n"
    f"💰 Your points: {user['points']:,}\n\n"
    f"You can earn more points by completing tasks!\n"
    f"📋 Go to Tasks to start earning."
)

        await update.message.reply_text(
            text,
            reply_markup=menu_keyboard(lang)
        )
        return

    # First-time user → language selection
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(MSG["en"]["lang_button"], callback_data="lang_en"),
        InlineKeyboardButton(MSG["am"]["lang_button"], callback_data="lang_am"),
    ]])

    await update.message.reply_text(
        MSG["en"]["language_prompt"],
        reply_markup=kb
    )

# ── Onboarding: Language → Age → ToS ─────────────────────────────────────────


async def cb_lang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = q.data.split("_")[1]
    t = lc(lang)
    await q.delete_message()
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(t["age_continue"], callback_data=f"age_yes_{lang}"),
        InlineKeyboardButton(t["age_exit"], callback_data=f"age_no_{lang}"),
    ]])
    await ctx.bot.send_message(q.from_user.id, t["age_text"], reply_markup=kb)


async def cb_age_yes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = lang_from(q.data)
    t = lc(lang)
    await q.delete_message()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t["tos_read"], url=TOS_URL)],
        [InlineKeyboardButton(t["tos_continue"], callback_data=f"tos_yes_{lang}"),
         InlineKeyboardButton(t["tos_exit"], callback_data=f"tos_no_{lang}")],
    ])
    await ctx.bot.send_message(q.from_user.id, t["tos_text"], reply_markup=kb)


async def cb_age_no(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = lang_from(q.data)
    await q.delete_message()
    await ctx.bot.send_message(q.from_user.id, lc(lang)["exit_message"])


async def cb_tos_yes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = lang_from(q.data)
    uid = q.from_user.id
    await get_or_create_user(uid, q.from_user.username, lang)
    await q.delete_message()
    await ctx.bot.send_message(uid, lc(lang)["welcome_final"], reply_markup=menu_keyboard(lang))


async def cb_tos_no(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = lang_from(q.data)
    await q.delete_message()
    await ctx.bot.send_message(q.from_user.id, lc(lang)["exit_message"])


# ── Main menu callbacks ───────────────────────────────────────────────────────


async def cb_menu_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = lang_from(q.data)
    await q.edit_message_text(lc(lang)["menu_title"], reply_markup=menu_keyboard(lang))


async def cb_menu_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = lang_from(q.data)
    user = await get_user(q.from_user.id)
    if not user:
        return
    uname = f"📛 Username: @{user['username']}\n" if user["username"] else ""
    text = (
        f"👤 *Profile*\n\n"
        f"🆔 ID: `{user['id']}`\n"
        f"{uname}"
        f"⭐ Level: {user['level']}\n"
        f"💰 Points: {user['points']:,}"
    )
    await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb(lang))


async def cb_menu_points(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = lang_from(q.data)
    t = lc(lang)
    user = await get_user(q.from_user.id)
    if not user:
        return
    text = (
        f"💰 *Your Points*\n\n"
        f"⭐ Level: {user['level']}\n"
        f"💰 Balance: {user['points']:,} pts\n\n"
        f"Earn more by completing tasks and claiming your daily reward!"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t["btn_daily"], callback_data=f"daily_{lang}")],
        [InlineKeyboardButton(t["btn_back"], callback_data=f"menu_back_{lang}")],
    ])
    await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def cb_daily(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    lang = lang_from(q.data)
    result = await claim_daily(q.from_user.id)
    if result["ok"]:
        await q.answer(f"✅ You claimed {result['pts']} pts as your daily reward!", show_alert=True)
    else:
        await q.answer(lc(lang)["daily_already"], show_alert=True)


async def cb_menu_rewards(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = lang_from(q.data)
    t = lc(lang)
    rewards = await get_active_rewards()
    if not rewards:
        await q.edit_message_text(t["no_rewards"], reply_markup=back_kb(lang))
        return
    lines = "\n\n".join(
        f"• *{r['title']}* — {r['cost']:,} pts" + (f"\n  {r['description']}" if r["description"] else "")
        for r in rewards
    )
    await q.edit_message_text(
        f"{t['rewards_title']}\n\n{lines}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_kb(lang),
    )


async def cb_menu_lb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = lang_from(q.data)
    uid = q.from_user.id
    medals = ["🥇", "🥈", "🥉"]
    top = await get_leaderboard(3)
    rank = await get_user_rank(uid)
    user = await get_user(uid)
    lines = "\n".join(
        f"{medals[i] if i < 3 else f'#{i+1}'} `{u['id']}` — {u['points']:,} pts"
        for i, u in enumerate(top)
    ) or "No entries yet."
    your_rank = f"\n\n📊 Your Rank: *#{rank}*\nYour Points: *{user['points']:,}*" if user else ""
    await q.edit_message_text(
        f"{lc(lang)['lb_public_title']}\n\n{lines}{your_rank}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_kb(lang),
    )


async def cb_menu_ads(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("📺 Ads coming soon!", show_alert=True)


async def cb_menu_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = lang_from(q.data)
    t = lc(lang)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t["btn_change_lang"], callback_data=f"settings_lang_{lang}")],
        [InlineKeyboardButton(t["btn_back"], callback_data=f"menu_back_{lang}")],
    ])
    await q.edit_message_text(t["settings_title"], parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def cb_settings_lang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(MSG["en"]["lang_button"], callback_data="switch_lang_en"),
        InlineKeyboardButton(MSG["am"]["lang_button"], callback_data="switch_lang_am"),
    ]])
    await q.edit_message_text(MSG["en"]["language_prompt"], reply_markup=kb)


async def cb_switch_lang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    new_lang = q.data.split("_")[2]
    await set_user_lang(q.from_user.id, new_lang)
    await q.answer("Language updated!", show_alert=True)
    await q.edit_message_text(lc(new_lang)["menu_title"], reply_markup=menu_keyboard(new_lang))


# ── Tasks (card-by-card) ──────────────────────────────────────────────────────


async def show_task_card(q, lang: str, index: int):
    uid = q.from_user.id
    tasks = await get_active_tasks()
    done_ids = await get_user_completed_task_ids(uid)
    t = lc(lang)

    if not tasks:
        await q.edit_message_text(t["no_tasks"], reply_markup=back_kb(lang))
        return

    index = max(0, min(index, len(tasks) - 1))
    task = tasks[index]
    done = task["id"] in done_ids
    total = len(tasks)

    text = (
        f"📋 *Task {index + 1} of {total}*\n\n"
        f"*{task['title']}*"
        + (f"\n{task['description']}" if task["description"] else "")
        + f"\n\n💰 Reward: *{task['points']:,} pts*"
        + ("\n✅ *Completed*" if done else "")
    )

    rows = []
    if done:
        rows.append([InlineKeyboardButton("✅ Already Completed", callback_data=f"task_already_{lang}")])
    elif task["link"]:
        rows.append([InlineKeyboardButton("📢 Join Channel", url=task["link"])])
        rows.append([InlineKeyboardButton(
            f"✅ Verify Joined  (+{task['points']} pts)",
            callback_data=f"task_claim_{task['id']}_{lang}",
        )])
    else:
        rows.append([InlineKeyboardButton(
            f"🚀 Open App  (+{task['points']} pts)",
            web_app=WebAppInfo(url=APP_URL),
        )])
        rows.append([InlineKeyboardButton("✅ Mark as Done", callback_data=f"task_claim_{task['id']}_{lang}")])

    if total > 1:
        prev_i = (index - 1 + total) % total
        next_i = (index + 1) % total
        rows.append([
            InlineKeyboardButton("◀️", callback_data=f"tasks_page_{prev_i}_{lang}"),
            InlineKeyboardButton(f"{index + 1} / {total}", callback_data=f"task_noop_{lang}"),
            InlineKeyboardButton("▶️", callback_data=f"tasks_page_{next_i}_{lang}"),
        ])

    rows.append([InlineKeyboardButton(t["btn_back"], callback_data=f"menu_back_{lang}")])
    await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows))


async def cb_menu_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await show_task_card(q, lang_from(q.data), 0)


async def cb_tasks_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
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
    task_id = int(parts[2])
    lang = parts[3]
    uid = q.from_user.id

    tasks = await get_active_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        await q.answer()
        return

    if await has_completed_task(uid, task_id):
        await q.answer(lc(lang)["task_already"], show_alert=True)
        return

    await complete_task(uid, task_id, task["points"])
    await q.answer(f"✅ Task \"{task['title']}\" completed! +{task['points']} pts", show_alert=True)

    current_index = next((i for i, t in enumerate(tasks) if t["id"] == task_id), 0)
    await show_task_card(q, lang, (current_index + 1) % len(tasks))


# ── Admin helpers ─────────────────────────────────────────────────────────────


async def resolve_target(arg: str):
    """Return (user_id, display_label) from @username or numeric string, or None if not found."""
    if arg.startswith("@") or not arg.lstrip("-").isdigit():
        user = await get_user_by_username(arg)
        if not user:
            return None
        label = f"@{user['username']}" if user["username"] else f"`{user['id']}`"
        return user["id"], label
    uid = int(arg)
    user = await get_user(uid)
    label = f"@{user['username']}" if (user and user["username"]) else f"`{uid}`"
    return uid, label


# ── Admin commands ────────────────────────────────────────────────────────────


async def cmd_addadmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_admin(uid):
        await update.message.reply_text(MSG["en"]["not_authorized"])
        return
    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text(
            "Usage: `/addadmin @username` or `/addadmin <user_id>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    target = await resolve_target(parts[1].strip())
    if not target:
        await update.message.reply_text("⚠️ User not found. They must have started the bot first.")
        return
    target_id, label = target
    if await is_admin(target_id):
        await update.message.reply_text(MSG["en"]["admin_already_exists"])
        return
    await add_admin(target_id, uid)
    await update.message.reply_text(f"✅ Admin added: {label}", parse_mode=ParseMode.MARKDOWN)


async def cmd_removeadmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_admin(uid):
        await update.message.reply_text(MSG["en"]["not_authorized"])
        return
    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text(
            "Usage: `/removeadmin @username` or `/removeadmin <user_id>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    target = await resolve_target(parts[1].strip())
    if not target:
        await update.message.reply_text("⚠️ User not found. They must have started the bot first.")
        return
    target_id, label = target
    if target_id == ADMIN_USER_ID:
        await update.message.reply_text(MSG["en"]["admin_is_primary"])
        return
    record = await get_admin_record(target_id)
    if not record:
        await update.message.reply_text(MSG["en"]["admin_not_found"])
        return
    if uid != ADMIN_USER_ID and record["created_by"] != uid:
        await update.message.reply_text(MSG["en"]["admin_not_yours"])
        return
    await remove_admin(target_id)
    await update.message.reply_text(f"✅ Admin removed: {label}", parse_mode=ParseMode.MARKDOWN)


async def cmd_addtask(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_admin(uid):
        await update.message.reply_text(MSG["en"]["not_authorized"])
        return
    body = update.message.text.replace("/addtask", "", 1).strip()
    if not body:
        await update.message.reply_text(
            "📋 *Add a Task*\n\n*Format:*\n`/addtask Title | https://link (optional) | points (optional)`\n\n"
            "*Examples:*\n"
            "• `/addtask Join our channel | https://t.me/falahbetofficial | 200`\n"
            "• `/addtask Open the App | | 150`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    parts = [p.strip() for p in body.split("|")]
    title = parts[0] if parts else ""
    link = parts[1] if len(parts) > 1 and parts[1] else None
    try:
        points = int(parts[2]) if len(parts) > 2 and parts[2] else (200 if link else 150)
    except ValueError:
        points = 200 if link else 150
    if not title:
        await update.message.reply_text("⚠️ Task title is required.")
        return
    task = await create_task(title, "", points, link)
    await update.message.reply_text(
        f"✅ Task created: *{task['title']}* (+{task['points']} pts)",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_listtasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_admin(uid):
        await update.message.reply_text(MSG["en"]["not_authorized"])
        return
    tasks = await get_all_tasks()
    if not tasks:
        await update.message.reply_text("📭 No tasks yet. Use /addtask to create one.")
        return
    rows = []
    for task in tasks:
        status = "✅ ON" if task["active"] else "🔴 OFF"
        toggle = "off" if task["active"] else "on"
        rows.append([InlineKeyboardButton(
            f"{status} | {task['title']} (+{task['points']} pts)",
            callback_data=f"adm_task_toggle_{task['id']}_{toggle}",
        )])
    await update.message.reply_text(
        "📋 *All Tasks* — tap to toggle on/off:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def cb_adm_task_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await is_admin(q.from_user.id):
        await q.answer(MSG["en"]["not_authorized"], show_alert=True)
        return
    parts = q.data.split("_")
    task_id = int(parts[3])
    new_state = parts[4] == "on"
    await toggle_task(task_id, new_state)
    await q.answer("✅ Task enabled" if new_state else "🔴 Task disabled", show_alert=True)
    tasks = await get_all_tasks()
    rows = []
    for task in tasks:
        status = "✅ ON" if task["active"] else "🔴 OFF"
        toggle = "off" if task["active"] else "on"
        rows.append([InlineKeyboardButton(
            f"{status} | {task['title']} (+{task['points']} pts)",
            callback_data=f"adm_task_toggle_{task['id']}_{toggle}",
        )])
    await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(rows))


async def cmd_addreward(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_admin(uid):
        await update.message.reply_text(MSG["en"]["not_authorized"])
        return
    body = update.message.text.replace("/addreward", "", 1).strip()
    if not body:
        await update.message.reply_text(
            "🎁 *Add a Reward*\n\n*Format:*\n`/addreward Title | Description | cost`\n\n"
            "*Example:*\n`/addreward VIP Badge | Exclusive badge for top players | 5000`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    parts = [p.strip() for p in body.split("|")]
    title = parts[0] if parts else ""
    description = parts[1] if len(parts) > 1 else ""
    try:
        cost = int(parts[2]) if len(parts) > 2 and parts[2] else 1000
    except ValueError:
        cost = 1000
    if not title:
        await update.message.reply_text("⚠️ Reward title is required.")
        return
    reward = await create_reward(title, description, cost)
    await update.message.reply_text(
        f"✅ Reward created: *{reward['title']}* ({reward['cost']:,} pts)",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_adminstats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_admin(uid):
        await update.message.reply_text(MSG["en"]["not_authorized"])
        return
    tasks = await get_all_tasks()
    rewards = await get_active_rewards()
    users = await get_all_users()
    active_count = sum(1 for t in tasks if t["active"])
    await update.message.reply_text(
        f"📊 *Admin Stats*\n\n"
        f"👥 Total Users: {len(users)}\n"
        f"📋 Active Tasks: {active_count} / {len(tasks)}\n"
        f"🎁 Active Rewards: {len(rewards)}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_adminlb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_admin(uid):
        await update.message.reply_text(MSG["en"]["not_authorized"])
        return
    top = await get_leaderboard(10)
    lines = "\n".join(
        f"#{i+1} {'@' + u['username'] + ' — ' if u['username'] else ''}`{u['id']}` — {u['points']:,} pts"
        for i, u in enumerate(top)
    ) or "No entries yet."
    await update.message.reply_text(
        f"🏆 *Admin Leaderboard — Top 10*\n\n{lines}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_admin(uid):
        await update.message.reply_text(MSG["en"]["not_authorized"])
        return
    body = update.message.text.replace("/broadcast", "", 1).strip()
    if not body:
        await update.message.reply_text(
            "Usage: `/broadcast Your message here`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    users = await get_all_users()
    if not users:
        await update.message.reply_text("📭 No registered users yet.")
        return
    await update.message.reply_text(f"📣 Sending to {len(users)} users…")
    sent = failed = 0
    for user in users:
        try:
            await ctx.bot.send_message(
                user["id"],
                f"📣 *Message from Admin*\n\n{body}",
                parse_mode=ParseMode.MARKDOWN,
            )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await update.message.reply_text(
        f"✅ Broadcast complete\n\n📨 Sent: {sent}\n❌ Failed: {failed} (blocked/deleted bots)"
    )


async def cmd_listcommands(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_admin(uid):
        await update.message.reply_text(MSG["en"]["not_authorized"])
        return
    await update.message.reply_text(
        "🛠 *Admin Commands*\n\n"
        "*Users & Admins*\n"
        "/addadmin @username — Promote a user to admin\n"
        "/removeadmin @username — Remove an admin you added\n\n"
        "*Tasks*\n"
        "/addtask — Show task creation guide\n"
        "/listtasks — List all tasks with enable/disable toggles\n\n"
        "*Rewards*\n"
        "/addreward — Show reward creation guide\n\n"
        "*Stats & Leaderboard*\n"
        "/adminstats — Task & reward counts\n"
        "/adminlb — Full top\\-10 leaderboard with usernames\n\n"
        "*Broadcast*\n"
        "/broadcast <message> — Send a message to all users\n\n"
        "*Help*\n"
        "/listcommands — Show this list\n"
        "/userinfo @username — Look up any user's profile",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_userinfo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_admin(uid):
        await update.message.reply_text(MSG["en"]["not_authorized"])
        return
    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text(
            "Usage: `/userinfo @username` or `/userinfo <user_id>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    target = await resolve_target(parts[1].strip())
    if not target:
        await update.message.reply_text("⚠️ User not found. They must have started the bot first.")
        return
    target_id, _ = target
    user = await get_user(target_id)
    if not user:
        await update.message.reply_text("⚠️ User not found.")
        return
    done_ids = await get_user_completed_task_ids(target_id)
    joined = user["created_at"].strftime("%d %b %Y") if user["created_at"] else "Unknown"
    lang_label = "🇪🇹 Amharic" if user["lang"] == "am" else "🇬🇧 English"
    uname = f"📛 Username: @{user['username']}\n" if user["username"] else ""
    await update.message.reply_text(
        f"👤 *User Info*\n\n"
        f"🆔 ID: `{user['id']}`\n"
        f"{uname}"
        f"🌐 Language: {lang_label}\n"
        f"⭐ Level: {user['level']}\n"
        f"💰 Points: {user['points']:,}\n"
        f"✅ Tasks Done: {len(done_ids)}\n"
        f"📅 Joined: {joined}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── App startup ───────────────────────────────────────────────────────────────
async def create_tables():
    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            username TEXT,
            lang TEXT DEFAULT 'en',
            points INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            daily_claimed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS admins (
            user_id BIGINT PRIMARY KEY,
            role TEXT DEFAULT 'admin',
            created_by BIGINT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            points INTEGER DEFAULT 0,
            link TEXT,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS task_completions (
            user_id BIGINT NOT NULL,
            task_id INTEGER NOT NULL,
            completed_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (user_id, task_id)
        );

        CREATE TABLE IF NOT EXISTS rewards (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            cost INTEGER NOT NULL,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)

async def post_init(app: Application):
    global pool

    pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=2,
        max_size=10,
        ssl="require"
    )

    await create_tables()
    await seed_tasks()

    print("✅ DB ready")

def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Onboarding
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(cb_lang,    pattern=r"^lang_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_age_yes, pattern=r"^age_yes_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_age_no,  pattern=r"^age_no_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_tos_yes, pattern=r"^tos_yes_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_tos_no,  pattern=r"^tos_no_(en|am)$"))

    # Menu
    app.add_handler(CallbackQueryHandler(cb_menu_back,     pattern=r"^menu_back_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_menu_profile,  pattern=r"^menu_profile_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_menu_points,   pattern=r"^menu_points_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_menu_tasks,    pattern=r"^menu_tasks_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_menu_rewards,  pattern=r"^menu_rewards_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_menu_lb,       pattern=r"^menu_lb_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_menu_ads,      pattern=r"^menu_ads_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_menu_settings, pattern=r"^menu_settings_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_settings_lang, pattern=r"^settings_lang_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_switch_lang,   pattern=r"^switch_lang_(en|am)$"))

    # Points / Daily
    app.add_handler(CallbackQueryHandler(cb_daily, pattern=r"^daily_(en|am)$"))

    # Tasks
    app.add_handler(CallbackQueryHandler(cb_menu_tasks,  pattern=r"^menu_tasks_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_tasks_page,  pattern=r"^tasks_page_\d+_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_task_noop,   pattern=r"^task_noop_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_task_already,pattern=r"^task_already_(en|am)$"))
    app.add_handler(CallbackQueryHandler(cb_task_claim,  pattern=r"^task_claim_\d+_(en|am)$"))

    # Admin callbacks
    app.add_handler(CallbackQueryHandler(cb_adm_task_toggle, pattern=r"^adm_task_toggle_\d+_(on|off)$"))

    # Admin commands
    app.add_handler(CommandHandler("addadmin",     cmd_addadmin))
    app.add_handler(CommandHandler("removeadmin",  cmd_removeadmin))
    app.add_handler(CommandHandler("addtask",      cmd_addtask))
    app.add_handler(CommandHandler("listtasks",    cmd_listtasks))
    app.add_handler(CommandHandler("addreward",    cmd_addreward))
    app.add_handler(CommandHandler("adminstats",   cmd_adminstats))
    app.add_handler(CommandHandler("adminlb",      cmd_adminlb))
    app.add_handler(CommandHandler("broadcast",    cmd_broadcast))
    app.add_handler(CommandHandler("listcommands", cmd_listcommands))
    app.add_handler(CommandHandler("userinfo",     cmd_userinfo))

    print("🤖 Falah.bet bot started (Python)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
