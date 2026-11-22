"""看板数据层：只读连接 + 启动时一次性预计算。

口径来源：docs/指标口径表.md。思路与参考写法不同——不在 SQL 里递归展开日期，
而是在 Python 里为每个房源建一张“按天可售日历”（在线期间且未被房东关房的日子），
再按月、按区聚合；订单、评论等只用简单的 GROUP BY 拉汇总行。
"""
from __future__ import annotations

import sqlite3
import statistics
from bisect import bisect_left
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, getcontext

getcontext().prec = 40


FIRST_DAY = date(2023, 10, 1)
LAST_DAY = date(2026, 9, 30)
SNAPSHOT_DAY = "2026-09-30"          # 房型结构 / 地理点的截止日
CURRENT_MONTH = "2026-09"
YOY_MONTH = "2025-09"
MOM_MONTH = "2026-08"
DIST_FROM, DIST_TO = "2026-07-01", "2026-09-30"  # 价格分布：2026Q3
COMPARE_MIN, COMPARE_MAX = "2024-10-01", "2026-09-30"


def connect() -> sqlite3.Connection:
    # 只读打开；相对路径以仓库根目录为工作目录（README 的启动命令即在根目录执行）
    return sqlite3.connect("file:data/homestay.db?mode=ro", uri=True)


# ---------------------------------------------------------------- 舍入
def half_up(value, places: int):
    """四舍五入（half-up，远离零）。value 可为 int / Decimal / float / None。"""
    if value is None:
        return None
    d = value if isinstance(value, Decimal) else Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    q = Decimal(1).scaleb(-places)
    return float(d.quantize(q, rounding=ROUND_HALF_UP))


def ratio(num, den, places: int):
    if not den:
        return None
    return half_up(Decimal(num) / Decimal(den), places)


def diff(cur, base, places: int):
    if cur is None or base is None:
        return None
    return half_up(Decimal(repr(cur)) - Decimal(repr(base)), places)


def rel_change(cur, base, places: int = 4):
    if cur is None or base is None or base == 0:
        return None
    return half_up(Decimal(repr(cur)) / Decimal(repr(base)) - 1, places)


# ---------------------------------------------------------------- 日期工具
def all_days() -> list[str]:
    out, d = [], FIRST_DAY
    while d <= LAST_DAY:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


ROOM_ORDER = ["独立单间", "一居室", "两居室", "三居室"]


def room_order(room_type: str):
    """价格分布按房型由小到大展示；未知房型排在最后。"""
    return (ROOM_ORDER.index(room_type) if room_type in ROOM_ORDER else len(ROOM_ORDER), room_type)


def quarter_of(ym: str) -> str:
    return f"{ym[:4]}Q{(int(ym[5:7]) - 1) // 3 + 1}"


class Dashboard:
    """启动时把所有视角需要的结果算好放在内存里。"""

    def __init__(self) -> None:
        self.days = all_days()
        self.months = sorted({d[:7] for d in self.days})
        con = connect()
        try:
            self._load(con)
        finally:
            con.close()
        self._build()

    # ------------------------------------------------------------ 读取
    def _load(self, con: sqlite3.Connection) -> None:
        self.meta = dict(con.execute("SELECT key, value FROM meta"))
        self.districts = [
            {"district_id": r[0], "name": r[1]}
            for r in con.execute("SELECT district_id, name FROM districts ORDER BY district_id")
        ]
        self.district_ids = [d["district_id"] for d in self.districts]
        self.district_name = {d["district_id"]: d["name"] for d in self.districts}

        self.listings = con.execute(
            "SELECT listing_id, district_id, room_type, online_date, offline_date, lat, lon "
            "FROM listings ORDER BY listing_id"
        ).fetchall()
        self.listing_district = {r[0]: r[1] for r in self.listings}

        self.blocks: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for lid, s, e in con.execute("SELECT listing_id, start_date, end_date FROM owner_blocks"):
            self.blocks[lid].append((s, e))

        # 已完成订单：按房源 × 入住月 汇总晚数与金额
        self.done_by_listing_month = con.execute(
            """
            SELECT listing_id, substr(checkin_date, 1, 7), SUM(nights), SUM(total_amount)
            FROM bookings
            WHERE status = '完成'
            GROUP BY listing_id, substr(checkin_date, 1, 7)
            """
        ).fetchall()

        # 已完成订单：按区 × 入住日 汇总晚数（对比视角任意区间用）
        self.done_by_district_day = con.execute(
            """
            SELECT x.district_id, b.checkin_date, SUM(b.nights)
            FROM bookings AS b
            INNER JOIN listings AS x USING (listing_id)
            WHERE b.status = '完成'
            GROUP BY x.district_id, b.checkin_date
            """
        ).fetchall()

        # 评论：按区 × 评论月，有效评分条数与总分
        self.review_rows = con.execute(
            """
            SELECT x.district_id, substr(r.review_date, 1, 7), COUNT(r.rating), SUM(r.rating)
            FROM reviews AS r
            INNER JOIN listings AS x USING (listing_id)
            GROUP BY x.district_id, substr(r.review_date, 1, 7)
            """
        ).fetchall()

        # 订单数（含取消）：按区 × 入住月 × 渠道
        self.channel_rows = con.execute(
            """
            SELECT x.district_id, substr(b.checkin_date, 1, 7), b.channel, COUNT(*)
            FROM bookings AS b
            INNER JOIN listings AS x USING (listing_id)
            GROUP BY 1, 2, 3
            """
        ).fetchall()

        # 2026Q3 已完成订单每晚价
        self.price_rows = con.execute(
            """
            SELECT x.district_id, x.room_type, b.nightly_price
            FROM bookings AS b
            INNER JOIN listings AS x USING (listing_id)
            WHERE b.status = '完成' AND b.checkin_date >= ? AND b.checkin_date <= ?
            """,
            (DIST_FROM, DIST_TO),
        ).fetchall()

        self.market_rows = con.execute(
            "SELECT district_id, month, occupancy_rate FROM market_benchmark"
        ).fetchall()

    # ------------------------------------------------------------ 预计算
    def _build(self) -> None:
        days, n_days = self.days, len(self.days)
        day_pos = {d: i for i, d in enumerate(days)}
        month_of_day = [d[:7] for d in days]

        # 1) 每个房源的按天可售日历 → 房源×月 可售晚数；区×天 可售晚数
        sellable_lm: dict[tuple[str, str], int] = defaultdict(int)
        district_daily = {d: [0] * n_days for d in self.district_ids}
        for lid, did, _rt, online, offline, _lat, _lon in self.listings:
            start = bisect_left(days, online)               # 第一天 >= online_date
            stop = n_days if offline is None else bisect_left(days, offline)  # offline 当天起不可售
            if start >= stop:
                continue
            open_days = [True] * (stop - start)
            for b_from, b_to in self.blocks.get(lid, ()):
                lo = max(bisect_left(days, b_from), start)
                hi = min(bisect_left(days, b_to) + (1 if b_to in day_pos else 0), stop)
                for i in range(lo, hi):
                    open_days[i - start] = False
            daily = district_daily[did]
            for k, ok in enumerate(open_days):
                if ok:
                    i = start + k
                    sellable_lm[(lid, month_of_day[i])] += 1
                    daily[i] += 1

        # 2) 月度：可售晚数、成交晚数、收入（只计有可售晚数的房源×月）
        scopes = [""] + self.district_ids
        acc = {s: defaultdict(lambda: [0, 0, 0]) for s in scopes}  # ym -> [sellable, nights, revenue]
        for (lid, ym), n in sellable_lm.items():
            did = self.listing_district[lid]
            acc[""][ym][0] += n
            acc[did][ym][0] += n
        for lid, ym, nights, revenue in self.done_by_listing_month:
            if sellable_lm.get((lid, ym), 0) <= 0:
                continue
            did = self.listing_district[lid]
            for s in ("", did):
                acc[s][ym][1] += nights
                acc[s][ym][2] += revenue

        # 3) 月度评分
        rating_acc = {s: defaultdict(lambda: [0, 0]) for s in scopes}  # ym -> [count, sum]
        for did, ym, cnt, total in self.review_rows:
            for s in ("", did):
                rating_acc[s][ym][0] += cnt
                rating_acc[s][ym][1] += total or 0

        self.monthly: dict[str, dict[str, dict]] = {}
        for s in scopes:
            rows = {}
            for ym in sorted(acc[s]):
                sellable, nights, revenue = acc[s][ym]
                if sellable <= 0:
                    continue
                cnt, total = rating_acc[s].get(ym, (0, 0))
                rows[ym] = {
                    "occupancy": ratio(nights, sellable, 4),
                    "adr": ratio(revenue, nights, 2) if nights else None,
                    "revpar": ratio(revenue, sellable, 2),
                    "rating": ratio(total, cnt, 2) if cnt >= 5 else None,
                }
            self.monthly[s] = rows

        # 4) 对比视角：区×天 前缀和
        self.sell_prefix = {}
        self.sold_prefix = {}
        sold_daily = {d: [0] * n_days for d in self.district_ids}
        for did, day, nights in self.done_by_district_day:
            i = day_pos.get(day)
            if i is not None and did in sold_daily:
                sold_daily[did][i] += nights
        for did in self.district_ids:
            for src, dst in ((district_daily[did], self.sell_prefix), (sold_daily[did], self.sold_prefix)):
                pre = [0]
                for v in src:
                    pre.append(pre[-1] + v)
                dst[did] = pre
        self.day_pos = day_pos
        self.compare_cache: dict[tuple[str, str], dict] = {}

        # 5) 渠道结构（含取消单），按季度
        ch = {s: defaultdict(lambda: defaultdict(int)) for s in scopes}  # q -> channel -> count
        for did, ym, channel, cnt in self.channel_rows:
            q = quarter_of(ym)
            for s in ("", did):
                ch[s][q][channel] += cnt
        self.channels = sorted({r[2] for r in self.channel_rows})
        self.structure: dict[str, dict] = {}

        # 6) 截至 2026-09-30 在线的房源
        online_now = [
            r for r in self.listings
            if r[3] <= SNAPSHOT_DAY and (r[4] is None or r[4] > SNAPSHOT_DAY)
        ]

        for s in scopes:
            quarters = sorted(ch[s])
            share = {c: [] for c in self.channels}
            for q in quarters:
                total = sum(ch[s][q].values())
                for c in self.channels:
                    share[c].append(ratio(ch[s][q].get(c, 0), total, 4) or 0.0)
            share = {c: v for c, v in share.items() if any(ch[s][q].get(c, 0) for q in quarters)}
            mix = defaultdict(int)
            for r in online_now:
                if s in ("", r[1]):
                    mix[r[2]] += 1
            self.structure[s] = {
                "quarters": quarters,
                "channel_share": share,
                "room_type_mix": [{"room_type": k, "n": mix[k]} for k in sorted(mix)],
            }

        # 7) 价格分布
        prices = {s: defaultdict(list) for s in scopes}
        for did, rt, p in self.price_rows:
            prices[""][rt].append(p)
            prices[did][rt].append(p)
        self.distribution = {}
        for s in scopes:
            out = []
            for rt in sorted(prices[s], key=room_order):
                vals = sorted(prices[s][rt])
                if len(vals) >= 2:
                    q1, med, q3 = statistics.quantiles(vals, n=4, method="inclusive")
                else:
                    q1 = med = q3 = float(vals[0])
                out.append({"room_type": rt, "n": len(vals), "min": vals[0], "q1": q1,
                            "median": med, "q3": q3, "max": vals[-1]})
            self.distribution[s] = {"room_types": out}

        # 8) 地理点
        self.geo = {
            s: {"points": [
                {"listing_id": r[0], "lat": r[5], "lon": r[6], "district_id": r[1], "room_type": r[2]}
                for r in online_now if s in ("", r[1])
            ]}
            for s in scopes
        }

        # 9) 指标卡 / 趋势
        self.kpi = {}
        self.trend = {}
        for s in scopes:
            m = self.monthly[s]
            cur, yoy, mom = m.get(CURRENT_MONTH, {}), m.get(YOY_MONTH, {}), m.get(MOM_MONTH, {})

            def change(base):
                return {
                    "occupancy": diff(cur.get("occupancy"), base.get("occupancy"), 4),
                    "adr": rel_change(cur.get("adr"), base.get("adr")),
                    "revpar": rel_change(cur.get("revpar"), base.get("revpar")),
                    "rating": diff(cur.get("rating"), base.get("rating"), 2),
                }

            self.kpi[s] = {
                "month": CURRENT_MONTH,
                "occupancy": cur.get("occupancy"),
                "adr": cur.get("adr"),
                "revpar": cur.get("revpar"),
                "rating": cur.get("rating"),
                "yoy": change(yoy),
                "mom": change(mom),
            }
            months = [ym for ym in self.months if ym in m]
            self.trend[s] = {
                "months": months,
                "occupancy": [m[ym]["occupancy"] for ym in months],
                "adr": [m[ym]["adr"] for ym in months],
                "revpar": [m[ym]["revpar"] for ym in months],
                "rating": [m[ym]["rating"] for ym in months],
            }

        # 预热缺省对比区间
        self.compare("2026-07-01", "2026-09-30")

    # ------------------------------------------------------------ 对比
    def _district_occupancy(self, start: str, end: str) -> dict[str, float | None]:
        i, j = self.day_pos[start], self.day_pos[end] + 1
        out = {}
        for did in self.district_ids:
            sell = self.sell_prefix[did][j] - self.sell_prefix[did][i]
            sold = self.sold_prefix[did][j] - self.sold_prefix[did][i]
            out[did] = ratio(sold, sell, 4)
        return out

    def _market(self, start: str, end: str) -> dict[str, float | None]:
        lo, hi = start[:7], end[:7]
        bucket: dict[str, list[float]] = defaultdict(list)
        for did, month, rate in self.market_rows:
            if lo <= month <= hi:
                bucket[did].append(rate)
        return {did: half_up(sum(v) / len(v), 4) if v else None for did, v in bucket.items()}

    def compare(self, start: str, end: str) -> dict:
        key = (start, end)
        if key in self.compare_cache:
            return self.compare_cache[key]
        prev_start = minus_one_year(start)
        prev_end = minus_one_year(end)
        cur = self._district_occupancy(start, end)
        prev = self._district_occupancy(prev_start, prev_end)
        market = self._market(start, end)
        result = {
            "start": start,
            "end": end,
            "districts": [
                {
                    "district_id": did,
                    "name": self.district_name[did],
                    "occupancy": cur[did],
                    "occupancy_prev_year": prev[did],
                    "market_occupancy": market.get(did),
                }
                for did in self.district_ids
            ],
        }
        if len(self.compare_cache) < 256:
            self.compare_cache[key] = result
        return result


def minus_one_year(day: str) -> str:
    d = date.fromisoformat(day)
    try:
        return d.replace(year=d.year - 1).isoformat()
    except ValueError:  # 2 月 29 日
        return d.replace(year=d.year - 1, day=28).isoformat()
