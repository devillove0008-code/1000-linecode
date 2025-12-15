#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Mast SEO + Admin Telegram Bot
- python-telegram-bot v21.6
- SQLite DB
Features:
- /start sends IMAGE + Inline Buttons (Support/Channel/Owner + Social links)
- Broadcast (admin only, safe rate-limited, logs)
- Ban / Unban (admin)
- /info /ping /uptime /help /stats
- Instagram SEO tools:
    /caption <topic> [style]
    /hashtags <topic> [n=25] [lang=hinglish|english|hindi]
    /seo <topic> (caption + hashtags + posting tips)
"""

import os
import re
import time
import json
import math
import sqlite3
import random
import logging
import traceback
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# -----------------------------
# ENV
# -----------------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0").strip() or "0")
BOT_NAME = os.getenv("BOT_NAME", "MastSEO_Bot").strip() or "MastSEO_Bot"
DB_PATH = os.getenv("DB_PATH", "bot.db").strip() or "bot.db"

START_IMAGE_URL = os.getenv("START_IMAGE_URL", "").strip()

SUPPORT_URL = os.getenv("SUPPORT_URL", "").strip() or "https://t.me/"
CHANNEL_URL = os.getenv("CHANNEL_URL", "").strip() or "https://t.me/"
OWNER_URL = os.getenv("OWNER_URL", "").strip() or "https://t.me/"

INSTAGRAM_URL = os.getenv("INSTAGRAM_URL", "").strip() or "https://instagram.com/"
YOUTUBE_URL = os.getenv("YOUTUBE_URL", "").strip() or "https://youtube.com/"
FACEBOOK_URL = os.getenv("FACEBOOK_URL", "").strip() or "https://facebook.com/"
SNAPCHAT_URL = os.getenv("SNAPCHAT_URL", "").strip() or "https://snapchat.com/add/"

BRAND_TAG = os.getenv("BRAND_TAG", "@YourBrand").strip() or "@YourBrand"
BROADCAST_DELAY = float(os.getenv("BROADCAST_DELAY", "0.06").strip() or "0.06")

if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN missing in .env")
if OWNER_ID == 0:
    print("⚠️ OWNER_ID missing. Admin features will be blocked.")

# -----------------------------
# LOGGING
# -----------------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger("mast-seo-bot")

START_TIME = time.time()

# -----------------------------
# HELP / TEXT
# -----------------------------
HELP_TEXT = (
    f"🤖 *{BOT_NAME}* Commands\n\n"
    "🧩 Basic:\n"
    "• /start - Menu + Image\n"
    "• /help - Commands\n"
    "• /info - Your info\n"
    "• /ping - Latency\n"
    "• /uptime - Bot uptime\n\n"
    "📈 SEO Tools (Instagram):\n"
    "• /caption <topic> [style]\n"
    "   styles: viral | aesthetic | attitude | love | sad | business | hindi | english\n"
    "• /hashtags <topic> [n=25] [lang=hinglish]\n"
    "• /seo <topic> - caption + hashtags + tips\n\n"
    "👑 Admin:\n"
    "• /stats - bot stats\n"
    "• /ban <user_id> [reason]\n"
    "• /unban <user_id>\n"
    "• /broadcast <message>\n"
)

MENU_TEXT = (
    f"✨ *Welcome to {BOT_NAME}*\n\n"
    "Choose an option below 👇\n"
    "Instagram SEO, Captions, Hashtags, Admin tools, Broadcast ✅"
)

RULES_TEXT = (
    "📌 *Rules*\n"
    "• Spam / Flood मत करो\n"
    "• Abuse नहीं\n"
    "• Wrong use पर ban हो सकता है\n"
)

ABOUT_TEXT = (
    f"ℹ️ *About {BOT_NAME}*\n"
    "• Fast & clean bot\n"
    "• SEO tools + Admin controls\n\n"
    f"Brand: {BRAND_TAG}\n"
)

# -----------------------------
# DB
# -----------------------------
class DB:
    def __init__(self, path: str):
        self.path = path
        self._init()

    def conn(self):
        return sqlite3.connect(self.path)

    def _init(self):
        with self.conn() as c:
            cur = c.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users(
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    joined_at INTEGER,
                    last_seen INTEGER,
                    is_banned INTEGER DEFAULT 0,
                    ban_reason TEXT DEFAULT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS broadcasts(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER,
                    message TEXT,
                    created_at INTEGER,
                    sent_ok INTEGER DEFAULT 0,
                    sent_fail INTEGER DEFAULT 0
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS meta(
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
            """)
            c.commit()

    def upsert_user(self, user_id: int, first_name: str, username: str):
        ts = int(time.time())
        with self.conn() as c:
            c.execute("""
                INSERT INTO users(user_id, first_name, username, joined_at, last_seen)
                VALUES(?,?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                    first_name=excluded.first_name,
                    username=excluded.username,
                    last_seen=excluded.last_seen
            """, (user_id, first_name or "", username or "", ts, ts))
            c.commit()

    def set_last_seen(self, user_id: int):
        ts = int(time.time())
        with self.conn() as c:
            c.execute("UPDATE users SET last_seen=? WHERE user_id=?", (ts, user_id))
            c.commit()

    def is_banned(self, user_id: int) -> Tuple[bool, Optional[str]]:
        with self.conn() as c:
            row = c.execute("SELECT is_banned, ban_reason FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                return (False, None)
            return (row[0] == 1, row[1])

    def ban(self, user_id: int, reason: str):
        ts = int(time.time())
        with self.conn() as c:
            c.execute("""
                INSERT INTO users(user_id, first_name, username, joined_at, last_seen, is_banned, ban_reason)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                    is_banned=1,
                    ban_reason=excluded.ban_reason
            """, (user_id, "", "", ts, ts, 1, reason))
            c.commit()

    def unban(self, user_id: int):
        with self.conn() as c:
            c.execute("UPDATE users SET is_banned=0, ban_reason=NULL WHERE user_id=?", (user_id,))
            c.commit()

    def stats(self) -> Dict[str, int]:
        with self.conn() as c:
            users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            banned = c.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
            return {"users": users, "banned": banned}

    def user_ids_active(self) -> List[int]:
        with self.conn() as c:
            rows = c.execute("SELECT user_id FROM users WHERE is_banned=0").fetchall()
            return [r[0] for r in rows]

    def log_broadcast(self, admin_id: int, message: str) -> int:
        ts = int(time.time())
        with self.conn() as c:
            cur = c.cursor()
            cur.execute("INSERT INTO broadcasts(admin_id, message, created_at) VALUES(?,?,?)", (admin_id, message, ts))
            c.commit()
            return cur.lastrowid

    def update_broadcast_result(self, bid: int, ok: int, fail: int):
        with self.conn() as c:
            c.execute("UPDATE broadcasts SET sent_ok=?, sent_fail=? WHERE id=?", (ok, fail, bid))
            c.commit()

db = DB(DB_PATH)

# -----------------------------
# UTILS
# -----------------------------
def is_admin(update: Update) -> bool:
    u = update.effective_user
    return bool(u and OWNER_ID and u.id == OWNER_ID)

def esc_md(s: str) -> str:
    if s is None:
        return ""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!])", r"\\\1", s)

def uptime_str() -> str:
    seconds = int(time.time() - START_TIME)
    d = seconds // 86400
    seconds %= 86400
    h = seconds // 3600
    seconds %= 3600
    m = seconds // 60
    s = seconds % 60
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)

async def asleep(sec: float):
    import asyncio
    await asyncio.sleep(sec)

# -----------------------------
# FLOOD CONTROL (simple)
# -----------------------------
@dataclass
class Flood:
    window: int = 8
    limit: int = 7
    bucket: Dict[int, List[int]] = None

    def __post_init__(self):
        if self.bucket is None:
            self.bucket = {}

    def hit(self, uid: int) -> bool:
        now = int(time.time())
        lst = self.bucket.get(uid, [])
        lst = [t for t in lst if now - t <= self.window]
        lst.append(now)
        self.bucket[uid] = lst
        return len(lst) > self.limit

FLOOD = Flood()

async def guard(update: Update) -> bool:
    u = update.effective_user
    if not u:
        return True
    db.upsert_user(u.id, u.first_name or "", u.username or "")
    db.set_last_seen(u.id)

    banned, reason = db.is_banned(u.id)
    if banned:
        text = "⛔ You are banned."
        if reason:
            text += f"\nReason: {esc_md(reason)}"
        try:
            await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass
        return False

    if not is_admin(update) and FLOOD.hit(u.id):
        try:
            await update.effective_message.reply_text("⚠️ Flood detected! Thoda slow bhejo.")
        except Exception:
            pass
        return False

    return True

# -----------------------------
# KEYBOARDS
# -----------------------------
def kb_main(admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📈 Instagram SEO", callback_data="seo_menu"),
            InlineKeyboardButton("🧩 Help", callback_data="help"),
        ],
        [
            InlineKeyboardButton("📌 Rules", callback_data="rules"),
            InlineKeyboardButton("ℹ️ About", callback_data="about"),
        ],
        [
            InlineKeyboardButton("🆘 Support", url=SUPPORT_URL),
            InlineKeyboardButton("📣 Channel", url=CHANNEL_URL),
        ],
        [
            InlineKeyboardButton("👑 Owner", url=OWNER_URL),
            InlineKeyboardButton("❌ Close", callback_data="close"),
        ],
        [
            InlineKeyboardButton("📸 Instagram", url=INSTAGRAM_URL),
            InlineKeyboardButton("▶️ YouTube", url=YOUTUBE_URL),
        ],
        [
            InlineKeyboardButton("📘 Facebook", url=FACEBOOK_URL),
            InlineKeyboardButton("👻 Snapchat", url=SNAPCHAT_URL),
        ],
    ]
    if admin:
        rows.insert(1, [InlineKeyboardButton("📣 Broadcast", callback_data="admin_broadcast_help")])
        rows.insert(2, [InlineKeyboardButton("🛡 Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)

def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="home")]])

def kb_seo_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧠 Caption Generator", callback_data="cap_help")],
        [InlineKeyboardButton("🏷 Hashtag Generator", callback_data="hash_help")],
        [InlineKeyboardButton("🚀 Full SEO Pack", callback_data="seo_help")],
        [InlineKeyboardButton("⬅️ Back", callback_data="home")],
    ])

def kb_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("🛑 Ban Help", callback_data="admin_ban_help")],
        [InlineKeyboardButton("✅ Unban Help", callback_data="admin_unban_help")],
        [InlineKeyboardButton("📣 Broadcast Help", callback_data="admin_broadcast_help")],
        [InlineKeyboardButton("⬅️ Back", callback_data="home")],
    ])

# -----------------------------
# Instagram SEO Engine (heuristic generator)
# -----------------------------
CAPTION_TEMPLATES = {
    "viral": [
        "{topic} 🔥\n\nAaj ka mood: {hook}\n\n{cta}\n{brand}",
        "Stop scrolling ❗\n{topic} 💥\n\n{hook}\n\n{cta}\n{brand}",
        "{topic} 🚀\n\n{hook}\n\nTag your friend 🤝\n{brand}",
    ],
    "aesthetic": [
        "{topic} ✨\n\nsoft vibes • calm mind • clean goals\n\n{cta}\n{brand}",
        "golden hour feelings 🌅\n{topic}\n\n{hook}\n{brand}",
    ],
    "attitude": [
        "{topic} 😈\n\n{hook}\n\n{cta}\n{brand}",
        "Level up mode ON ⚡\n{topic}\n\n{hook}\n{brand}",
    ],
    "love": [
        "{topic} ❤️\n\n{hook}\n\n{cta}\n{brand}",
        "Uske bina bhi main complete hoon… but {topic} 🫶\n\n{brand}",
    ],
    "sad": [
        "{topic} 🥀\n\n{hook}\n\n{brand}",
        "कुछ बातें अधूरी रह जाती हैं… {topic} 💔\n\n{brand}",
    ],
    "business": [
        "{topic} 📈\n\n{hook}\n\nSave this ✅\n{brand}",
        "Real growth = consistency.\n{topic}\n\n{cta}\n{brand}",
    ],
    "hindi": [
        "{topic} ✨\n\n{hook}\n\n{cta}\n{brand}",
        "आज का सोच: {hook}\n\n{topic}\n\n{brand}",
    ],
    "english": [
        "{topic}\n\n{hook}\n\n{cta}\n{brand}",
    ],
}

HOOKS = [
    "Consistency beats motivation.",
    "Bas ek baar try kar… phir habit ban जाएगी.",
    "Small steps, big results.",
    "Focus on progress, not perfection.",
    "Energy is everything.",
    "No excuses. Just work.",
    "Kuch karna hai to aaj hi.",
    "Dil se kiya to output bhi real hoga.",
]

CTAS = [
    "✅ Save this post",
    "💬 Comment your thoughts",
    "🔁 Share with your friend",
    "📌 Follow for more",
    "❤️ Like if you agree",
]

LANG_TAGS = {
    "english": ["reels", "explorepage", "trending", "viralreels", "instagood", "contentcreator"],
    "hindi": ["reelsindia", "hindireels", "india", "desivibes", "hindiquotes", "desireels"],
    "hinglish": ["reelsindia", "trendingreels", "viral", "explore", "instareels", "desivibes"],
}

NICHES = {
    "bike": ["splendor", "bike", "bikelife", "rider", "ride", "motorcycle", "biker"],
    "love": ["love", "couple", "romance", "relationship", "pyar", "meriJaan"],
    "sad": ["sad", "broken", "heartbreak", "alone", "sadquotes", "mood"],
    "fitness": ["fitness", "gym", "workout", "health", "motivation", "fitlife"],
    "business": ["business", "startup", "hustle", "entrepreneur", "marketing", "growth"],
    "music": ["music", "song", "lyrics", "beats", "artist", "audio"],
    "travel": ["travel", "wanderlust", "trip", "vacation", "explore", "journey"],
    "editing": ["capcut", "videoediting", "editing", "template", "reelsedit", "creator"],
}

def guess_niche(topic: str) -> str:
    t = (topic or "").lower()
    for k, words in NICHES.items():
        for w in words:
            if w.lower() in t:
                return k
    # fallback keywords
    if any(x in t for x in ["gym", "workout", "fitness"]): return "fitness"
    if any(x in t for x in ["love", "jaan", "gf", "bf"]): return "love"
    if any(x in t for x in ["sad", "alone", "breakup"]): return "sad"
    if any(x in t for x in ["edit", "capcut", "template"]): return "editing"
    return "music"

def make_caption(topic: str, style: str = "viral") -> str:
    style = (style or "viral").lower().strip()
    if style not in CAPTION_TEMPLATES:
        style = "viral"
    template = random.choice(CAPTION_TEMPLATES[style])

    hook = random.choice(HOOKS)
    cta = random.choice(CTAS)
    brand = f"{BRAND_TAG}"

    text = template.format(topic=topic, hook=hook, cta=cta, brand=brand)
    return text.strip()

def normalize_hashtag(tag: str) -> str:
    tag = re.sub(r"[^a-zA-Z0-9_]", "", tag)
    tag = tag.strip("_")
    if not tag:
        return ""
    return "#" + tag

def topic_keywords(topic: str) -> List[str]:
    # Extract simple keywords
    t = (topic or "").strip()
    # split by spaces and punctuation
    parts = re.split(r"[\s,.;:!?\-_/]+", t)
    parts = [p for p in parts if p and len(p) >= 3]
    # Unique preserve order
    seen = set()
    out = []
    for p in parts:
        lp = p.lower()
        if lp not in seen:
            seen.add(lp)
            out.append(lp)
    return out[:10]

def make_hashtags(topic: str, n: int = 25, lang: str = "hinglish") -> List[str]:
    lang = (lang or "hinglish").lower().strip()
    if lang not in LANG_TAGS:
        lang = "hinglish"

    niche = guess_niche(topic)
    base = []
    # topic keywords => hashtags
    for kw in topic_keywords(topic):
        base.append(kw)
        base.append(kw + "reels")
        base.append("the" + kw)
    # niche tags
    base += NICHES.get(niche, [])
    # language tags
    base += LANG_TAGS[lang]
    # always useful tags
    base += ["reels", "reelsvideo", "viral", "explore", "explorepage", "instareels", "instagramreels"]

    # Clean + shuffle
    base = [b.lower() for b in base if b]
    random.shuffle(base)

    tags = []
    seen = set()
    for b in base:
        ht = normalize_hashtag(b)
        if not ht:
            continue
        if ht in seen:
            continue
        seen.add(ht)
        tags.append(ht)
        if len(tags) >= n:
            break

    # If still short, add fillers
    fillers = ["creator", "content", "trend", "reelitfeelit", "instadaily", "viralvideo", "newpost", "foryou"]
    for f in fillers:
        if len(tags) >= n:
            break
        ht = normalize_hashtag(f)
        if ht not in seen:
            seen.add(ht)
            tags.append(ht)

    return tags[:n]

def seo_pack(topic: str) -> str:
    cap = make_caption(topic, "viral")
    tags = make_hashtags(topic, 25, "hinglish")
    niche = guess_niche(topic)
    tips = [
        "📌 Posting tips:",
        "• Reel length: 6–12 sec (hook in first 1 sec)",
        "• Use 3–5 keywords in first line",
        "• Keep hashtags 18–25 (mix niche + broad)",
        "• Pin top comment with keyword + CTA",
        "• Best time (India): 7–10 PM / 12–2 PM",
        f"• Niche guessed: {niche}",
    ]
    return f"🧠 *Caption*\n{esc_md(cap)}\n\n🏷 *Hashtags*\n{esc_md(' '.join(tags))}\n\n{esc_md(chr(10).join(tips))}"

# -----------------------------
# Commands
# -----------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return

    admin = is_admin(update)
    # If image URL present, send as photo with caption
    if START_IMAGE_URL:
        try:
            await update.effective_message.reply_photo(
                photo=START_IMAGE_URL,
                caption=MENU_TEXT,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main(admin=admin),
            )
            return
        except Exception:
            # fallback to text
            pass

    await update.effective_message.reply_text(
        MENU_TEXT,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_main(admin=admin),
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    await update.effective_message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    u = update.effective_user
    c = update.effective_chat
    text = (
        "🧾 *Info*\n"
        f"• Name: {esc_md(u.full_name)}\n"
        f"• Username: @{esc_md(u.username or 'N/A')}\n"
        f"• User ID: `{u.id}`\n"
        f"• Chat ID: `{c.id}`\n"
        f"• Admin: `{is_admin(update)}`\n"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    t0 = time.time()
    m = await update.effective_message.reply_text("🏓 Pinging...")
    ms = int((time.time() - t0) * 1000)
    await m.edit_text(f"🏓 Pong! `{ms}ms`", parse_mode=ParseMode.MARKDOWN)

async def uptime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    await update.effective_message.reply_text(f"⏱ Uptime: `{uptime_str()}`", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    if not is_admin(update):
        await update.effective_message.reply_text("⛔ Admin only.")
        return
    s = db.stats()
    text = (
        "📊 *Stats*\n"
        f"• Users: `{s['users']}`\n"
        f"• Banned: `{s['banned']}`\n"
        f"• Uptime: `{uptime_str()}`\n"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    if not is_admin(update):
        await update.effective_message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.effective_message.reply_text("Use: /ban <user_id> [reason]")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("❌ user_id must be number.")
        return
    reason = " ".join(context.args[1:]).strip() or "No reason"
    db.ban(uid, reason)
    await update.effective_message.reply_text(f"✅ Banned `{uid}`\nReason: {esc_md(reason)}", parse_mode=ParseMode.MARKDOWN)
    try:
        await context.bot.send_message(uid, f"⛔ You are banned.\nReason: {reason}")
    except Exception:
        pass

async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    if not is_admin(update):
        await update.effective_message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.effective_message.reply_text("Use: /unban <user_id>")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("❌ user_id must be number.")
        return
    db.unban(uid)
    await update.effective_message.reply_text(f"✅ Unbanned `{uid}`", parse_mode=ParseMode.MARKDOWN)
    try:
        await context.bot.send_message(uid, "✅ You are unbanned now.")
    except Exception:
        pass

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    if not is_admin(update):
        await update.effective_message.reply_text("⛔ Admin only.")
        return

    msg = " ".join(context.args).strip()
    if not msg:
        await update.effective_message.reply_text("Use: /broadcast <message>")
        return

    user_ids = db.user_ids_active()
    if not user_ids:
        await update.effective_message.reply_text("No users found.")
        return

    bid = db.log_broadcast(update.effective_user.id, msg)
    status = await update.effective_message.reply_text(
        f"📣 Broadcast started...\nUsers: {len(user_ids)}\nBroadcast ID: {bid}"
    )

    ok = 0
    fail = 0
    total = len(user_ids)
    last_edit = time.time()

    for i, uid in enumerate(user_ids, start=1):
        try:
            await context.bot.send_message(uid, msg)
            ok += 1
        except Exception:
            fail += 1

        # Rate limit
        await asleep(BROADCAST_DELAY)

        # Progress update
        if time.time() - last_edit > 2.5:
            last_edit = time.time()
            try:
                await status.edit_text(f"📣 Sending... {i}/{total}\n✅ OK: {ok} | ❌ Fail: {fail}")
            except Exception:
                pass

    db.update_broadcast_result(bid, ok, fail)
    await status.edit_text(f"✅ Broadcast done!\nTotal: {total}\n✅ OK: {ok}\n❌ Fail: {fail}\nID: {bid}")

async def caption_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    args = context.args
    if not args:
        await update.effective_message.reply_text("Use: /caption <topic> [style]\nExample: /caption splendor bike viral")
        return

    # last token might be style
    style = "viral"
    if args[-1].lower() in CAPTION_TEMPLATES.keys():
        style = args[-1].lower()
        topic = " ".join(args[:-1]).strip()
    else:
        topic = " ".join(args).strip()

    if not topic:
        await update.effective_message.reply_text("❌ Topic missing.")
        return

    cap = make_caption(topic, style)
    out = f"🧠 *Caption ({style})*\n{esc_md(cap)}"
    await update.effective_message.reply_text(out, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_seo_menu())

async def hashtags_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    args = context.args
    if not args:
        await update.effective_message.reply_text("Use: /hashtags <topic> [n=25] [lang=hinglish]\nExample: /hashtags bike reels 25 hinglish")
        return

    # parse optional n and lang at end
    lang = "hinglish"
    n = 25

    # Detect lang
    if args and args[-1].lower() in ("hinglish", "english", "hindi"):
        lang = args[-1].lower()
        args = args[:-1]

    # Detect n
    if args and re.fullmatch(r"\d{1,2}", args[-1]):
        n = max(10, min(30, int(args[-1])))
        args = args[:-1]

    topic = " ".join(args).strip()
    if not topic:
        await update.effective_message.reply_text("❌ Topic missing.")
        return

    tags = make_hashtags(topic, n=n, lang=lang)
    out = f"🏷 *Hashtags ({lang}, {n})*\n{esc_md(' '.join(tags))}"
    await update.effective_message.reply_text(out, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_seo_menu())

async def seo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    topic = " ".join(context.args).strip()
    if not topic:
        await update.effective_message.reply_text("Use: /seo <topic>\nExample: /seo Dr Zeus song reels")
        return
    out = seo_pack(topic)
    await update.effective_message.reply_text(out, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_seo_menu())

# -----------------------------
# Callback UI
# -----------------------------
async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    await q.answer()

    # Guard for callback
    fake_update = Update(update.update_id, callback_query=q)
    if not await guard(fake_update):
        return

    data = q.data or ""
    admin = is_admin(update)

    if data == "close":
        try:
            await q.message.delete()
        except Exception:
            await q.edit_message_text("Closed.")
        return

    if data == "home":
        if START_IMAGE_URL:
            try:
                await q.message.reply_photo(
                    photo=START_IMAGE_URL,
                    caption=MENU_TEXT,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb_main(admin=admin),
                )
                try:
                    await q.message.delete()
                except Exception:
                    pass
                return
            except Exception:
                pass

        await q.edit_message_text(MENU_TEXT, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_main(admin=admin))
        return

    if data == "help":
        await q.edit_message_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())
        return

    if data == "rules":
        await q.edit_message_text(RULES_TEXT, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())
        return

    if data == "about":
        await q.edit_message_text(ABOUT_TEXT, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())
        return

    if data == "seo_menu":
        await q.edit_message_text(
            "📈 *Instagram SEO Menu*\nChoose tool 👇",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_seo_menu(),
        )
        return

    if data == "cap_help":
        await q.edit_message_text(
            "🧠 *Caption Generator*\n"
            "Use:\n"
            "`/caption <topic> [style]`\n\n"
            "Example:\n"
            "`/caption splendor bike viral`\n"
            "`/caption meri jaan love`\n",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_seo_menu(),
        )
        return

    if data == "hash_help":
        await q.edit_message_text(
            "🏷 *Hashtag Generator*\n"
            "Use:\n"
            "`/hashtags <topic> [n=25] [lang=hinglish]`\n\n"
            "Example:\n"
            "`/hashtags bike reels 25 hinglish`\n"
            "`/hashtags dr zeus song 20 english`\n",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_seo_menu(),
        )
        return

    if data == "seo_help":
        await q.edit_message_text(
            "🚀 *Full SEO Pack*\n"
            "Use:\n"
            "`/seo <topic>`\n\n"
            "Example:\n"
            "`/seo capcut editing reels`\n",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_seo_menu(),
        )
        return

    if data == "admin_panel":
        if not admin:
            await q.edit_message_text("⛔ Admin only.", reply_markup=kb_back())
            return
        await q.edit_message_text("🛡 *Admin Panel*", parse_mode=ParseMode.MARKDOWN, reply_markup=kb_admin())
        return

    if data == "admin_stats":
        if not admin:
            await q.edit_message_text("⛔ Admin only.", reply_markup=kb_back())
            return
        s = db.stats()
        await q.edit_message_text(
            f"📊 *Stats*\n• Users: `{s['users']}`\n• Banned: `{s['banned']}`\n• Uptime: `{uptime_str()}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_admin(),
        )
        return

    if data == "admin_ban_help":
        await q.edit_message_text(
            "🛑 *Ban*\nUse:\n`/ban <user_id> [reason]`\nExample:\n`/ban 123456 spam`\n",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_admin(),
        )
        return

    if data == "admin_unban_help":
        await q.edit_message_text(
            "✅ *Unban*\nUse:\n`/unban <user_id>`\nExample:\n`/unban 123456`\n",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_admin(),
        )
        return

    if data == "admin_broadcast_help":
        await q.edit_message_text(
            "📣 *Broadcast*\nUse:\n`/broadcast <message>`\n\n"
            "⚠️ Tip: छोटा msg भेजो + ज्यादा spam मत करो.\n",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_admin() if admin else kb_back(),
        )
        return

    await q.edit_message_text("Unknown action.", reply_markup=kb_back())

# -----------------------------
# Text fallback
# -----------------------------
async def text_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    t = (update.effective_message.text or "").strip()
    if not t:
        return
    if t.lower() in ("hi", "hello", "hlo", "hey"):
        await update.effective_message.reply_text("👋 /start दबाओ menu के लिए.")
        return
    await update.effective_message.reply_text("🙂 Use /start or /help")

# -----------------------------
# Error handler
# -----------------------------
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    err = context.error
    log.error("Error: %s", err)
    tb = "".join(traceback.format_exception(type(err), err, err.__traceback__))
    if OWNER_ID:
        try:
            await context.bot.send_message(
                OWNER_ID,
                f"⚠️ Bot Error:\n`{esc_md(str(err))}`\n\n```{tb[:3500]}```",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

# -----------------------------
# App
# -----------------------------
def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("info", info_cmd))
    app.add_handler(CommandHandler("ping", ping_cmd))
    app.add_handler(CommandHandler("uptime", uptime_cmd))

    app.add_handler(CommandHandler("caption", caption_cmd))
    app.add_handler(CommandHandler("hashtags", hashtags_cmd))
    app.add_handler(CommandHandler("seo", seo_cmd))

    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))

    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_msg))

    app.add_error_handler(on_error)
    return app

def main():
    log.info("Starting %s ...", BOT_NAME)
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()