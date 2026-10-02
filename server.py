# language: Python 3.11, file: server.py, target: Render.com Docker
import asyncio
import random

from pydantic import BaseModel
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
]

def fmt_proxy(line: str):
    line = line.strip()
    # rsplit from right so hostnames with dots stay intact
    parts = line.rsplit(":", 3)
    if len(parts) != 4:
        return None
    host, port, user, pw = parts
    return f"http://{user}:{pw}@{host}:{port}"

async def send_view(url, proxy_str, ua, watch_seconds):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            proxy={"server": proxy_str} if proxy_str else None,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        ctx = await browser.new_context(
            user_agent=ua,
            viewport={"width": random.randint(390, 430), "height": random.randint(844, 932)},
            locale="en-US",
            timezone_id="America/New_York",
            is_mobile=True,
            has_touch=True,
        )
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
            window.chrome = {runtime: {}};
        """)
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_selector("video", timeout=20000)
            await page.evaluate("document.querySelector('video')?.play()")
            await asyncio.sleep(max(3.0, watch_seconds + random.uniform(-2, 2)))
            return True
        except Exception as e:
            print(f"view error: {e}")
            return False
        finally:
            await ctx.close()
            await browser.close()

class BotRequest(BaseModel):
    url: str
    views: int = 50
    watch_seconds: float = 10.0
    concurrency: int = 3
    proxies: list[str] = []

@app.post("/bot")
async def bot(req: BotRequest):
    proxy_lines = req.proxies
    formatted = [fmt_proxy(p) for p in proxy_lines]
    formatted = [p for p in formatted if p]

    print(f"received {len(proxy_lines)} proxies, {len(formatted)} valid")

    sem = asyncio.Semaphore(req.concurrency)
    results = {"success": 0, "fail": 0, "used_proxies": []}

    async def worker(raw, proxy_fmt):
        async with sem:
            print(f"trying proxy: {proxy_fmt}")
            ok = await send_view(req.url, proxy_fmt, random.choice(USER_AGENTS), req.watch_seconds)
            results["success" if ok else "fail"] += 1
            results["used_proxies"].append(raw)
            await asyncio.sleep(random.uniform(1.5, 4.0))

    pairs = list(zip(proxy_lines, formatted))[:req.views]
    if not pairs:
        print("no valid proxies — running bare")
        for _ in range(req.views):
            ok = await send_view(req.url, None, random.choice(USER_AGENTS), req.watch_seconds)
            results["success" if ok else "fail"] += 1
    else:
        await asyncio.gather(*[worker(r, f) for r, f in pairs])

    print(f"done: {results}")
    return results

@app.get("/")
async def home():
    return FileResponse("index.html")


@app.get("/ping")
async def ping():
    return {"status": "alive"}
