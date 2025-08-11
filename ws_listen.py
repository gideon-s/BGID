# ws_listen.py
import asyncio, json, websockets, argparse

async def listen(base, player_id):
    url = f"{base.replace('http', 'ws')}/ws/{player_id}"
    print(f"→ connecting {url}")
    async with websockets.connect(url) as ws:
        print("✓ connected. waiting for events…")
        try:
            async for msg in ws:
                try:
                    data = json.loads(msg)
                except json.JSONDecodeError:
                    data = {"type":"message","raw":msg}
                print(f"\n[WS:{player_id}] {json.dumps(data, indent=2)}")
        except websockets.ConnectionClosed as e:
            print(f"[WS:{player_id}] closed: {e.code} {e.reason}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--player", type=int, required=True)
    args = ap.parse_args()
    asyncio.run(listen(args.url, args.player))
