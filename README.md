# Stock Bot

Telegram bot ตอบข้อมูลหุ้น US + TH ผ่านชื่อย่อหรือคำสั่งภาษาธรรมชาติ
ใช้ yfinance + Pillow + Claude Haiku

## Features

- 📊 **ข้อมูลหุ้นตัวเดียว** — card รูปสีเขียว/แดงตามวัน + metrics + สรุปผลประกอบการล่าสุด
- 📈 **Top N gainers/losers** สำหรับ US + TH (N = 1–20)
- 🌟 **Magnificent 7** — AAPL, MSFT, GOOGL, AMZN, META, TSLA, NVDA
- 🇹🇭 **รองรับ SET** — auto-suffix `.BK` ถ้าหา US ไม่เจอ
- 🤖 **Fuzzy intent** — เข้าใจภาษาธรรมชาติ (เช่น "ขอดูเมกาที่ขึ้นเยอะวันนี้")
- 💵 **Currency-aware** — แสดง `$` / `฿` ตามตลาด

## Commands

### หุ้นตัวเดียว
- `AAPL` / `NVDA` / `$TSLA` — US
- `PTT.BK` / `KBANK.BK` หรือแค่ `PTT` (auto-fallback `.BK`)
- ภาษาธรรมชาติ: `ขอ aapl`, `ปตท ราคาเท่าไหร่`, `กสิกร ตอนนี้`, `ปูนใหญ่`

### Top movers
- สั้น: `top 10 ไทย`, `top10 thai`, `top 5 us`, `top10 เมกา`
- ใส่ `ลบ` / `ร่วง` ต่อเพื่อขอ losers — ไม่ใส่ = gainers (default)
- เต็มยศ: `top 10 หุ้นอเมริกาพุ่งแรงวันนี้`, `top 10 หุ้นไทยร่วงหนักวันนี้`
- ภาษาธรรมชาติ: `ขอดูเมกาที่ขึ้นเยอะวันนี้`, `หุ้นไทยตกหนัก 5 ตัว`

### Magnificent 7
- `mag 7`, `mag7`, `7mag`, `7 mag`, `7 นางฟ้า`, `หุ้น 7 นางฟ้า`, `7 angels`

## Architecture

```
User message
    │
    ▼
handle_message (bot.py)
    │
    ├─ regex _detect_mag7        → _handle_mag7_command
    ├─ regex _detect_top_command → _handle_top_command
    ├─ regex _extract_ticker     → _process_ticker
    │                                ├─ render_card     (Pillow)
    │                                ├─ format_metrics  (HTML <pre>)
    │                                └─ summarize_earnings (TTM stats)
    │
    └─ fallback (looks_like_stock_command)
       classify_with_llm (Claude Haiku → JSON intent)
       → route ไปยัง handler เดียวกับ regex
```

### ไฟล์

| ไฟล์ | บทบาท |
|---|---|
| [bot.py](bot.py) | Telegram entry, regex routing, LLM fallback |
| [stock.py](stock.py) | yfinance: `get_stock_metrics`, `get_earnings_payload`, `format_metrics` (HTML) |
| [screener.py](screener.py) | yfinance Screener: top movers (US+TH), intraday, batch quotes |
| [card.py](card.py) | Pillow: single-stock card (640×480) + smart logo bg detection |
| [list_card.py](list_card.py) | Pillow: top-movers list card + sparklines |
| [summarizer.py](summarizer.py) | Pure-Python earnings formatter (Revenue/EPS/ROIC/etc.) |
| [intent.py](intent.py) | Claude Haiku: fuzzy intent classifier (JSON), prompt-cached |
| [assets/fonts/](assets/fonts/) | Bundled Kanit (Thai+Latin) — Linux/Docker fallback |
| [Dockerfile](Dockerfile) | python:3.11-slim, runs `python -u bot.py` |
| [railway.toml](railway.toml) | Railway config: Dockerfile builder, always-restart |

### Data sources

- **yfinance** (Yahoo Finance) — quotes, fundamentals, quarterly statements, intraday, screener
- **Financial Modeling Prep** — `https://financialmodelingprep.com/image-stock/{SYMBOL}.png` สำหรับ logo
- **Anthropic Claude Haiku** — fuzzy intent classification + Thai company name → ticker

### Rendering

**Single stock card** ([card.py](card.py))
- 640×480 rounded card — เขียว `#00BA7B` ถ้า change ≥ 0, แดง `#FF4560` ถ้า < 0
- Logo: panel background ปรับอัตโนมัติ (ขาวหรือเทาเข้ม) ตามความสว่างของ logo shape
- Font: Sukhumvit Set (Mac dev) → Kanit (Linux/Docker fallback)

**List card** ([list_card.py](list_card.py))
- 720px กว้าง, สูง = title + N×170 + padding
- แต่ละแถว: tag pill (purple) + logo circle + symbol + sparkline + prev close + price + change pill
- Sparkline: `history(period="1d", interval="5m")` → fill area + line

**Earnings narrative** ([summarizer.py](summarizer.py))
- คำนวณ YoY/QoQ/Margin/ROIC ใน Python (deterministic)
- `🔥 Record High` เมื่อค่า latest = max ของ time series
- `Beat Est. / Miss Est.` จาก earnings surprise
- Format เป็น HTML `<pre>` column-aligned

### Intent classification

[bot.py](bot.py) ใช้ regex-first (เร็ว, ฟรี) ถ้าไม่ match จะ fallback ไป Claude Haiku **เฉพาะเมื่อ:**
- ข้อความ ≤ 120 ตัวอักษร **และ**
- มี keyword เกี่ยวหุ้น (top, หุ้น, mag, อเมริก, ไทย, gainers, …) **หรือ**
- ข้อความสั้น (≤ 30 ตัว) ที่มีตัวอักษรไทย

Cost: ~$0.00005/call (Haiku 4.5 + system prompt cached @ 90% off)

## Setup local

```bash
git clone <repo>
cd stockbot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# กรอก TELEGRAM_BOT_TOKEN + ANTHROPIC_API_KEY
python bot.py
```

### ตั้งค่า Telegram bot

1. คุยกับ [@BotFather](https://t.me/BotFather) → `/newbot` → ได้ token
2. `/setprivacy` → เลือก bot → **Disable** (ให้ bot เห็นข้อความทุกอันใน group)
3. Add bot เข้า group (ตั้งเป็น admin ก็ได้)

## Deploy (Railway)

1. Push ขึ้น GitHub
   ```bash
   git branch -M main
   git remote add origin git@github.com:<user>/stockbot.git
   git push -u origin main
   ```
2. [railway.app](https://railway.app) → Login ด้วย GitHub → **New Project** → **Deploy from GitHub repo**
3. Service → **Variables** tab → ใส่:
   - `TELEGRAM_BOT_TOKEN`
   - `ANTHROPIC_API_KEY`
4. Railway detect [Dockerfile](Dockerfile) + [railway.toml](railway.toml) อัตโนมัติ → build ~2–3 นาที
5. หยุด local bot ก่อนเพื่อไม่ให้ polling ชน
6. ดู Logs → `Bot starting (polling)…` = เสร็จ

ต้นทุน: Railway Hobby trial $5/เดือน — bot นี้กิน ~$3–4 รัน 24/7

## Tech stack

- Python 3.11+
- `python-telegram-bot==21.6` (polling)
- `yfinance>=1.2.0` (quotes + screener + intraday)
- `Pillow>=10.0.0` (card image rendering)
- `anthropic>=0.40.0` (Claude Haiku 4.5 — fuzzy intent)
- `python-dotenv` (config)

## Environment variables

| Variable | Required | คำอธิบาย |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✓ | จาก @BotFather |
| `ANTHROPIC_API_KEY` | ✓ | จาก console.anthropic.com (ใช้สำหรับ fuzzy intent) |

## Known limitations

- **yfinance** scrapes Yahoo — มี rate limit ระดับ IP ถ้าใช้หนักอาจ 429 (เปลี่ยน IP/ใช้ proxy ช่วยได้)
- **FMP logo** ไม่มีหุ้นไทยตัวเล็ก/warrant → fallback dark circle
- **Sparkline** ใช้ PIL line ไม่ anti-alias — เห็นเส้นแหลมๆ บนภาพขยาย
- **ROIC** approximate: `NetIncome_q × 4 / (Debt + Equity)` ไม่ใช่ TTM แท้ ใช้ค่ากำไรไตรมาส annualized
