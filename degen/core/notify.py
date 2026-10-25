"""Telegram notifier. Without a token it prints, so paper mode works with zero setup.
Sends retry on network errors; anything still undelivered is queued and resent next cycle."""
import os, time, asyncio, httpx
class Notifier:
    def __init__(self):
        self.tok, self.chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
        self.pending = []          # messages that failed every retry
        self.last_sent = time.time()

    async def _post(self, body):
        url = f"https://api.telegram.org/bot{self.tok}/sendMessage"
        for wait in (0, 5, 20):
            if wait: await asyncio.sleep(wait)
            try:
                async with httpx.AsyncClient(timeout=15) as h:
                    r = await h.post(url, json=body)
                    if r.status_code == 200: return True
                    print("[TG] send failed:", r.text[:200], flush=True)
                    if r.status_code == 400 and body.get("parse_mode"):  # odd symbol broke HTML: resend plain
                        body = {k: v for k, v in body.items() if k != "parse_mode"}
                        body["text"] = body["text"].replace("<b>", "").replace("</b>", "")
            except Exception as e:
                print("[TG] send error:", repr(e)[:150], flush=True)
        return False

    async def send(self, text, buttons=None):
        print("[TG]", text.replace("\n", " | "), flush=True)
        if not (self.tok and self.chat): return
        await self.flush()
        body = {"chat_id": self.chat, "text": text, "parse_mode": "HTML"}
        if buttons: body["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in buttons]]}
        if await self._post(body): self.last_sent = time.time()
        else: self.pending.append((time.strftime("%H:%M", time.gmtime(time.time() + 3600)), body))

    async def flush(self):
        """Resend queued messages (marked 'delayed') once the connection is back."""
        while self.pending:
            t, body = self.pending[0]
            b = dict(body); b["text"] = f"(delayed from {t} WAT)\n" + b["text"]
            if not await self._post(b): return
            self.pending.pop(0); self.last_sent = time.time()

    async def commands(self):
        """Return new text commands sent to the bot by the owner chat (e.g. /stats)."""
        if not (self.tok and self.chat): return []
        try:
            async with httpx.AsyncClient(timeout=10) as h:
                r = (await h.get(f"https://api.telegram.org/bot{self.tok}/getUpdates",
                                 params={"offset": getattr(self, "_off", 0), "timeout": 0})).json()
        except Exception:
            return []
        out = []
        for u in r.get("result", []):
            self._off = u["update_id"] + 1
            m = u.get("message") or {}
            if str((m.get("chat") or {}).get("id")) == str(self.chat) and m.get("text", "").startswith("/"):
                out.append(m["text"].split()[0].split("@")[0].lower())
        return out
