# Stock AI API

HTTP API ที่รับชื่อย่อหุ้น/คำสั่งภาษาธรรมชาติ (US + TH) แล้วตอบกลับเป็น **การ์ดรูป PNG**
ใช้ yfinance + Pillow + Claude Haiku — orchestrate ผ่าน **N8N** (N8N เป็นคนคุย Telegram)

> เดิมเป็น Telegram bot (polling) บน Railway — ตอนนี้ย้ายมาเป็น HTTP API stateless
> รัน self-host ด้วย Docker, N8N เป็นเจ้าของฝั่ง Telegram (Trigger → เรียก API → ส่งรูปกลับ)

## Features

- 📊 **ข้อมูลหุ้นตัวเดียว** — card รูปสีเขียว/แดงตามวัน + metrics + สรุปผลประกอบการล่าสุด
- 📈 **Top N gainers/losers** สำหรับ US + TH (N = 1–20)
- 🌟 **Magnificent 7** — AAPL, MSFT, GOOGL, AMZN, META, TSLA, NVDA
- 😱 **Fear & Greed** — CNN equity index + Crypto F&G (gauge + chart)
- 🇹🇭 **รองรับ SET** — auto-suffix `.BK` ถ้าหา US ไม่เจอ
- 🤖 **Fuzzy intent** — เข้าใจภาษาธรรมชาติ (เช่น "ขอดูเมกาที่ขึ้นเยอะวันนี้")
- 💵 **Currency-aware** — แสดง `$` / `฿` ตามตลาด

## Queries (ค่า `q` ที่ส่งเข้า API)

### หุ้นตัวเดียว
- `AAPL` / `NVDA` / `$TSLA` — US
- `PTT.BK` / `KBANK.BK` หรือแค่ `PTT` (auto-fallback `.BK`)
- ภาษาธรรมชาติ: `ขอ aapl`, `ปตท ราคาเท่าไหร่`, `กสิกร ตอนนี้`, `ปูนใหญ่`

### Top movers
- สั้น: `top 10 ไทย`, `top10 thai`, `top 5 us`, `top10 เมกา`
- ใส่ `ลบ` / `ร่วง` ต่อเพื่อขอ losers — ไม่ใส่ = gainers (default)
- ภาษาธรรมชาติ: `ขอดูเมกาที่ขึ้นเยอะวันนี้`, `หุ้นไทยตกหนัก 5 ตัว`

### อื่น ๆ
- Magnificent 7: `mag 7`, `mag7`, `7 นางฟ้า`, `7 angels`
- Fear & Greed: `fear greed`, `fng`, `ดัชนีความกลัว`
- Crypto F&G (คืน **2 รูป**): `crypto index`, `crypto fear greed`, `ดัชนีคริปโต`

## Architecture

```
Telegram user
    │
    ▼
N8N  (Telegram Trigger)
    │   POST http://stock-api:8000/api/v1/stocks/all  {"q": "<text>"}
    ▼
stock-api (FastAPI, app.py)
    │
    ▼
core.render_query(text)  ── routing เดิมของ bot ──┐
    ├─ _detect_crypto_fear_greed → _handle_crypto_fear_greed_command  (2 รูป)
    ├─ _detect_fear_greed        → _handle_fear_greed_command
    ├─ _detect_mag7              → _handle_mag7_command
    ├─ _detect_top_command       → _handle_top_command
    ├─ _extract_ticker           → _process_ticker  (chart card + report card)
    └─ fallback: looks_like_stock_command → classify_with_llm (Claude Haiku)
    │
    ▼  list[bytes] (PNG)
N8N  (base64 → binary → Send Photo)  →  Telegram user
```

### HTTP API contract

| Endpoint | Method | คืนค่า | ใช้ตอน |
|---|---|---|---|
| `/api/v1/stocks/all` | POST `{"q":"..."}` | JSON `{count, images:[base64 png...], error, query}` | **contract หลักของ N8N** — รองรับ 1..N รูป + error ไทยในตัว |
| `/api/v1/stocks` | GET `?q=...&i=0` / POST `{"q":"..."}` | `image/png` รูปที่ `i` (+header `X-Image-Count`) | manual test / เคสรูปเดียวง่าย ๆ |
| `/healthz` | GET | `{"status":"ok"}` | liveness probe |

- `/api/v1/stocks/all` คืน HTTP 200 เสมอ — เช็คผลจาก body: `count==0 && error!=null` = ไม่พบ/พัง, `count==0 && error==null` = เงียบ (เดิมบอทไม่ตอบ)
- `/api/v1/stocks` status: `204` (เงียบ) · `404` (ไม่พบหุ้น) · `502` (ดึงข้อมูลพัง) · `500`
- ถ้าตั้ง env `API_KEY` ต้องส่ง header `X-API-Key` ให้ตรง (ไม่ตั้ง = เปิด — เหมาะกับ network ภายใน)

### ไฟล์

| ไฟล์ | บทบาท |
|---|---|
| [core.py](core.py) | `render_query(text) -> list[bytes]` — routing + fetch + render (framework-agnostic) |
| [app.py](app.py) | FastAPI: `/api/v1/stocks`, `/api/v1/stocks/all`, `/healthz` |
| [bot.py](bot.py) | Telegram adapter (optional) — local smoke test ของ core |
| [stock.py](stock.py) | yfinance: `get_stock_metrics`, `get_earnings_payload`, FX, intraday |
| [screener.py](screener.py) | yfinance Screener: top movers (US+TH), intraday, batch quotes |
| [card.py](card.py) / [report_card.py](report_card.py) / [list_card.py](list_card.py) | Pillow card renderers |
| [fear_greed.py](fear_greed.py) / [crypto_fear_greed.py](crypto_fear_greed.py) | F&G index data + card render |
| [enrich.py](enrich.py) | คำอธิบาย/แท็กบริษัท (Claude) |
| [intent.py](intent.py) | Claude Haiku: fuzzy intent classifier (JSON), prompt-cached |
| [Dockerfile](Dockerfile) | python:3.11-slim, runs `uvicorn app:app` |
| [docker-compose.yml](docker-compose.yml) | server stack: stock-api + n8n + cloudflared |
| [.github/workflows/deploy.yml](.github/workflows/deploy.yml) | build → GHCR → SSH deploy |

### Data sources

- **yfinance** (Yahoo Finance) — quotes, fundamentals, quarterly statements, intraday, screener
- **Financial Modeling Prep** — logo `https://financialmodelingprep.com/image-stock/{SYMBOL}.png`
- **Anthropic Claude Haiku** — fuzzy intent + Thai company name → ticker + enrichment

## Local dev

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # กรอก ANTHROPIC_API_KEY (API_KEY ปล่อยว่างได้)

uvicorn app:app --reload --port 8000   # --reload: แก้ app.py/core.py/render แล้วเห็นผลทันที
```

ทดสอบ + ดูรูป:

```bash
# ติ๊กเกอร์ (รูปแรก = chart card; i=1 = report card)
curl "localhost:8000/api/v1/stocks?q=AAPL" -o a.png && open a.png

# crypto = 2 รูป → ใช้ /api/v1/stocks/all แล้ว decode base64 ทั้ง array
curl -s -X POST localhost:8000/api/v1/stocks/all -H 'content-type: application/json' \
  -d '{"q":"crypto index"}' \
  | python -c "import sys,json,base64; d=json.load(sys.stdin); [open(f'c{i}.png','wb').write(base64.b64decode(x)) for i,x in enumerate(d['images'])]"
open c0.png c1.png

# ลองยิง query แบบ interactive
open http://localhost:8000/docs
```

> รัน Telegram adapter เดิม (optional): ใส่ `TELEGRAM_BOT_TOKEN` ใน `.env` แล้ว `python bot.py`

## Deploy (self-host + GitHub Actions → GHCR)

**Auto-deploy:** push เข้า `main` → [.github/workflows/deploy.yml](.github/workflows/deploy.yml) build image → push `ghcr.io/siriphonnott/stock-ai-bot` → SSH เข้า server → `docker compose pull stock-api && up -d stock-api` (แตะแค่ stock-api ไม่ยุ่ง n8n/postgres)

> image มีโค้ดครบในตัว → **server ไม่ต้อง clone repo** แค่มี `docker-compose.yml` + `.env` ก็พอ

### ตั้งครั้งเดียวบน server (มี stack n8n + postgres + cloudflared อยู่แล้ว)

server มี compose อยู่แล้ว — แค่ **เพิ่ม service `stock-api`** เข้าไฟล์เดิม (ไม่มี `networks:` กำหนด → อยู่ default network เดียวกัน n8n เรียก `http://stock-api:8000` ได้เลย):

```yaml
  stock-api:
    image: ghcr.io/siriphonnott/stock-ai-bot:latest
    container_name: stock-api
    restart: unless-stopped
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - API_KEY=${API_KEY}          # optional shared secret; empty = open
    expose:
      - "8000"                       # internal-only; ไม่ publish ออก host
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

แล้วบน server:

```bash
cd <dir ที่มี docker-compose.yml>
# เพิ่ม ANTHROPIC_API_KEY (+ API_KEY ถ้าจะเปิด auth) ลงใน .env
echo "<GHCR_PAT>" | docker login ghcr.io -u siriphonNott --password-stdin   # ถ้า package private
docker compose pull stock-api
docker compose up -d stock-api
docker compose ps              # stock-api ควร healthy
```

- **stock-api** ใช้ `expose` (ไม่ใช่ `ports`) → เข้าถึงได้เฉพาะใน docker network ที่ `http://stock-api:8000` — ไม่หลุดออกเน็ต
- **n8n** เปิดสู่ public ผ่าน **Cloudflare Tunnel** ที่รันใน compose อยู่แล้ว (ไม่ต้องแตะ)
- [docker-compose.yml](docker-compose.yml) ในรีโปคือ **reference** ของ stack เต็ม (postgres + n8n + cloudflared + stock-api) — source of truth คือไฟล์บน server

### GitHub repo secrets (Settings → Secrets → Actions)

| Secret | คำอธิบาย |
|---|---|
| `SERVER_HOST` | IP/hostname ของ Hetzner server |
| `SERVER_USER` | deploy user (อยู่ใน docker group) |
| `SERVER_SSH_KEY` | private key (public อยู่ใน `~/.ssh/authorized_keys` ของ server) |
| `DEPLOY_PATH` | dir ที่มี `docker-compose.yml` บน server |
| `GHCR_USER` | `siriphonNott` |
| `GHCR_PAT` | PAT scope `read:packages` (เฉพาะถ้า GHCR package เป็น private) |

> push image จาก CI ใช้ `GITHUB_TOKEN` ในตัว (ไม่ต้องสร้าง secret) — ต้องมี `permissions: packages: write`

### N8N workflow

Telegram Trigger → HTTP Request (`POST http://stock-api:8000/api/v1/stocks/all`, body `{"q": "={{ $json.message.text }}"}`, ใส่ header `X-API-Key` ถ้าเปิด auth) → ถ้า `count==0 && error` ส่ง error ไทย, ไม่งั้น Split images → Convert base64 → binary → Telegram **Send Photo**

## Environment variables

| Variable | Required | คำอธิบาย |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✓ | console.anthropic.com — fuzzy intent + enrichment (stock-api) |
| `API_KEY` | – | shared secret ของ HTTP API (ว่าง = เปิด) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | server | DB ของ n8n |
| `N8N_HOST` | server | hostname ของ N8N (ใช้กับ tunnel) |
| `WEBHOOK_URL` | server | URL public ของ N8N เช่น `https://n8n.example.com/` |
| `N8N_ENCRYPTION_KEY` | server | random ยาว ๆ และ **คงที่** (ไม่งั้น credential ใน N8N พังตอน restart) |
| `CF_TUNNEL_TOKEN` | server | token ของ Cloudflare Named Tunnel |
| `TELEGRAM_BOT_TOKEN` | – | เฉพาะถ้ารัน `bot.py` เป็น smoke test |

## Tech stack

- Python 3.11+ · `fastapi` + `uvicorn[standard]` (HTTP API)
- `yfinance` (quotes + screener + intraday) · `Pillow` (card rendering)
- `anthropic` (Claude Haiku 4.5 — fuzzy intent + enrichment)
- `python-telegram-bot==21.6` (optional — bot.py smoke test)
- Docker + N8N + Cloudflare Tunnel (self-host)

## Known limitations

- **yfinance** scrapes Yahoo — มี rate limit ระดับ IP ถ้าใช้หนักอาจ 429 (เปลี่ยน IP/ใช้ proxy ช่วยได้)
- **FMP logo** ไม่มีหุ้นไทยตัวเล็ก/warrant → fallback dark circle
- **Sparkline** ใช้ PIL line ไม่ anti-alias — เห็นเส้นแหลม ๆ บนภาพขยาย
- **ROIC** approximate: `NetIncome_q × 4 / (Debt + Equity)` ใช้กำไรไตรมาส annualized
