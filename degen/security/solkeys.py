"""Base58 + ed25519 on-curve check, used to tell program-owned vaults (PDAs, off-curve) from real wallets."""
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def b58decode(s: str) -> bytes:
    n = 0
    for ch in s: n = n * 58 + B58.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + raw

P = 2**255 - 19
D = (-121665 * pow(121666, P - 2, P)) % P
def is_on_curve(pubkey: str) -> bool:
    b = b58decode(pubkey)
    if len(b) != 32: return False
    y = int.from_bytes(b, "little") & ((1 << 255) - 1)
    if y >= P: return False
    y2 = y * y % P
    u = (y2 - 1) % P; v = (D * y2 + 1) % P
    x2 = u * pow(v, P - 2, P) % P
    if x2 == 0: return True
    return pow(x2, (P - 1) // 2, P) == 1   # quadratic residue -> valid point
