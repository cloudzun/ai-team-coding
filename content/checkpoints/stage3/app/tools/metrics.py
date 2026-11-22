"""房源级指标的单一实现（口径按 docs/指标口径表.md）。

- 只读打开 homestay.db（mode=ro），启动后一次性载入内存，之后只做纯 Python 计算。
- 保留的指标（两规则版只用到这三个）：
  R12 单房源入住率（日历晚数 / 可售晚数 / 成交晚数 / 入住率 / 毛入住率）
  R13 单房源关房晚数（按原因拆分）
  R16 某日当前平日价与上一档平日价
- 比例用 Fraction 精确计算，展示值按四舍五入（half-up）保留位数；阈值判断用精确值。
"""
from __future__ import annotations

import sqlite3
import threading
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from app.config import ROOT

DB_PATH = ROOT / "data" / "homestay.db"

# 整改工单的问题类型（运营手册 F-01 的七类）
ISSUE_TYPES = ("噪音", "清洁", "入住指引", "设施", "沟通", "位置描述", "其他")


def connect_ro() -> sqlite3.Connection:
    """homestay.db 只读连接（mode=ro）。"""
    return sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True, check_same_thread=False)


def rnd(value, places: int):
    """精确值 → 四舍五入后的 float；None 原样返回。"""
    if value is None:
        return None
    frac = Fraction(value)
    d = Decimal(frac.numerator) / Decimal(frac.denominator)
    return float(d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def iter_days(start: str, end: str):
    d, last = date.fromisoformat(start), date.fromisoformat(end)
    while d <= last:
        yield d.isoformat()
        d += timedelta(days=1)


class Store:
    """homestay.db 的只读内存快照 + 指标函数。"""

    def __init__(self) -> None:
        con = connect_ro()
        try:
            self._load(con)
        finally:
            con.close()
        self._cache: dict[tuple, dict] = {}

    # ------------------------------------------------------------------ 载入
    def _load(self, con: sqlite3.Connection) -> None:
        self.listings: dict[str, dict] = {}
        for lid, did, rt, comm, owner, online, offline in con.execute(
            "SELECT listing_id, district_id, room_type, community, owner_id, online_date, offline_date "
            "FROM listings ORDER BY listing_id"
        ):
            self.listings[lid] = {"listing_id": lid, "district_id": did, "room_type": rt,
                                  "community": comm, "owner_id": owner,
                                  "online_date": online, "offline_date": offline}
        self.district_name = dict(con.execute("SELECT district_id, name FROM districts"))
        self.owner_email = dict(con.execute("SELECT owner_id, email FROM owners"))

        self.blocks: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for lid, s, e, reason in con.execute(
            "SELECT listing_id, start_date, end_date, reason FROM owner_blocks"
        ):
            self.blocks[lid].append((s, e, reason))

        self.done: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
        for lid, ci, nights, amount in con.execute(
            "SELECT listing_id, checkin_date, SUM(nights), SUM(total_amount) FROM bookings "
            "WHERE status = '完成' GROUP BY listing_id, checkin_date"
        ):
            self.done[lid].append((ci, nights, amount))

        self.prices: dict[str, list[tuple[str, int, int, str]]] = defaultdict(list)
        for lid, eff, wd, we, src in con.execute(
            "SELECT listing_id, effective_date, weekday_price, weekend_price, source "
            "FROM price_history ORDER BY listing_id, effective_date"
        ):
            self.prices[lid].append((eff, wd, we, src))

    # ------------------------------------------------------------------ 基础
    def exists(self, listing_id: str) -> bool:
        return listing_id in self.listings

    def online_on(self, listing_id: str, day: str) -> bool:
        x = self.listings[listing_id]
        return x["online_date"] <= day and (x["offline_date"] is None or x["offline_date"] > day)

    def online_listings(self, day: str) -> list[str]:
        return [lid for lid in self.listings if self.online_on(lid, day)]

    def _memo(self, key: tuple, fn):
        hit = self._cache.get(key)
        if hit is None:
            hit = fn()
            self._cache[key] = hit
        return hit

    def _blocked_days(self, listing_id: str, start: str, end: str, reason: str | None = None) -> set[str]:
        out: set[str] = set()
        for s, e, r in self.blocks.get(listing_id, ()):
            if reason is not None and r != reason:
                continue
            lo, hi = max(s, start), min(e, end)
            if lo <= hi:
                out.update(iter_days(lo, hi))
        return out

    # ------------------------------------------------------------------ R12
    def r12(self, listing_id: str, start: str, end: str) -> dict:
        """单房源入住率。exact_* 为精确值（阈值判断用），其余为展示值。"""
        def calc():
            x = self.listings[listing_id]
            blocked = self._blocked_days(listing_id, start, end)
            cal = avail = 0
            for d in iter_days(start, end):
                if d >= x["online_date"] and (x["offline_date"] is None or d < x["offline_date"]):
                    cal += 1
                    if d not in blocked:
                        avail += 1
            sold = sum(n for ci, n, _a in self.done.get(listing_id, ()) if start <= ci <= end)
            occ = Fraction(sold, avail) if avail else None
            gross = Fraction(sold, cal) if cal else None
            return {"calendar_nights": cal, "available_nights": avail, "sold_nights": sold,
                    "occupancy": rnd(occ, 4), "gross_occupancy": rnd(gross, 4),
                    "exact_occupancy": occ, "exact_gross_occupancy": gross}
        return self._memo(("r12", listing_id, start, end), calc)

    # ------------------------------------------------------------------ R13
    def r13(self, listing_id: str, start: str, end: str) -> dict[str, int]:
        """单房源关房晚数，按原因拆分（只计与期间重叠的部分）；无该原因则不出现。"""
        def calc():
            out = {}
            for reason in sorted({r for _s, _e, r in self.blocks.get(listing_id, ())}):
                n = len(self._blocked_days(listing_id, start, end, reason))
                if n:
                    out[reason] = n
            return out
        return self._memo(("r13", listing_id, start, end), calc)

    # ------------------------------------------------------------------ R16
    def r16(self, listing_id: str, day: str) -> dict | None:
        """day 当天的当前平日价（T-02）与上一档平日价。无价格记录返回 None。"""
        rows = [r for r in self.prices.get(listing_id, ()) if r[0] <= day]
        if not rows:
            return None
        eff, wd, we, src = rows[-1]
        prev = rows[-2][1] if len(rows) >= 2 else None
        pct = rnd(Fraction(wd, prev) - 1, 4) if prev else None
        return {"effective_date": eff, "current_price": wd, "weekend_price": we, "source": src,
                "previous_price": prev, "price_change_pct": pct}

    def price_history(self, listing_id: str, day: str) -> list[dict]:
        return [{"effective_date": e, "weekday_price": wd, "weekend_price": we, "source": s}
                for e, wd, we, s in self.prices.get(listing_id, ()) if e <= day]


_STORE: Store | None = None
_LOCK = threading.Lock()


def store() -> Store:
    """进程内单例（首次调用时载入，约数秒）。"""
    global _STORE
    if _STORE is None:
        with _LOCK:
            if _STORE is None:
                _STORE = Store()
    return _STORE
