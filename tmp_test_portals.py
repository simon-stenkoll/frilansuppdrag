"""Quick diagnostic: test each broker portal URL for HTTP status."""
import asyncio
import httpx

from src.config import BROKER_PORTALS

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


async def main():
    async with httpx.AsyncClient(headers=HEADERS, timeout=10, follow_redirects=True) as client:
        for portal in BROKER_PORTALS:
            name = portal["name"]
            url = portal["url"]
            try:
                resp = await client.get(url)
                print(f"  {resp.status_code}  {name:30s}  {url}")
            except Exception as e:
                print(f"  ERR  {name:30s}  {type(e).__name__}: {e}")

    print(f"\nTotal portals: {len(BROKER_PORTALS)}")


asyncio.run(main())
