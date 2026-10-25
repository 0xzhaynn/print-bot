"""Thin async clients for free/public endpoints (swap URLs/keys in config for paid tiers)."""
import httpx, asyncio
SOL = "So11111111111111111111111111111111111111112"

class Clients:
    def __init__(self, cfg):
        self.cfg = cfg
        self.http = httpx.AsyncClient(timeout=15, headers={"user-agent": "degen-autonomous/0.1"})
    async def close(self): await self.http.aclose()

    async def _get(self, url, **params):
        for attempt in range(5):
            r = await self.http.get(url, params=params or None)
            if r.status_code == 429: await asyncio.sleep(3 * (attempt + 1)); continue
            r.raise_for_status(); return r.json()
        r.raise_for_status()

    async def rpc(self, method, params):
        for attempt in range(3):
            r = await self.http.post(self.cfg["rpc_url"], json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            if r.status_code == 429: await asyncio.sleep(2 * (attempt + 1)); continue
            r.raise_for_status(); j = r.json()
            if "error" in j: raise RuntimeError(j["error"])
            return j["result"]
        r.raise_for_status()

    # discovery
    async def latest_profiles(self):
        d = await self._get(f'{self.cfg["dexscreener_base"]}/token-profiles/latest/v1')
        return [x for x in d if x.get("chainId") == "solana"]
    async def trending_boosts(self):
        d = await self._get(f'{self.cfg["dexscreener_base"]}/token-boosts/top/v1')
        return [x for x in d if x.get("chainId") == "solana"]
    async def pairs_for(self, mint):
        d = await self._get(f'{self.cfg["dexscreener_base"]}/token-pairs/v1/solana/{mint}')
        return d or []
    async def search(self, q):
        d = await self._get(f'{self.cfg["dexscreener_base"]}/latest/dex/search', q=q)
        return (d or {}).get("pairs") or []
    # risk
    async def rugcheck(self, mint):
        try: return await self._get(f'{self.cfg["rugcheck_base"]}/tokens/{mint}/report/summary')
        except Exception: return None
    async def rugcheck_full(self, mint):
        try: return await self._get(f'{self.cfg["rugcheck_base"]}/tokens/{mint}/report')
        except Exception: return None
    # execution quotes
    async def quote(self, input_mint, output_mint, amount, slippage_bps=300):
        return await self._get(f'{self.cfg["jupiter_base"]}/quote', inputMint=input_mint, outputMint=output_mint,
                               amount=str(int(amount)), slippageBps=slippage_bps)
