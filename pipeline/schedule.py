# -*- coding: utf-8 -*-
"""일정 시간 산정 — 이동시간·일자 창·도착 시각.

앱 레포의 `체류시간 산정/stay_schedule.js` 를 그대로 옮긴 것이다. 그쪽은
`Tour Planner.dc.html`(PoC) 안의 계산을 분리해 문서화한 것인데, **실제 서비스는
그 레포를 쓰지 않는다.** 프론트가 "09:00–10:10" 같은 시각 표기를 받으려면 누군가
이 계산을 해야 하고, 좌표·체류시간·운영시간이 전부 여기 있으므로 data-server 가
맡는다.

계산식과 상수는 `체류시간 산정/체류시간_산정_로직_설명.docx` 를 따른다. 근거가
있는 것은 이동시간 쪽이다 — 한국도로공사 고속도로 표정속도 92km/h, KTX 200km/h,
고속버스 110km/h. 장소별 체류시간(`stayMin`)은 편집 추정치다.

단위: 시간은 분, 거리는 km. 시각은 0시 기준 경과 분(09:00 = 540).
"""
import math
import re

# ── 상수 (산정_파라미터.csv 와 같은 값) ───────────────────────────────────
DAY_START = 9 * 60          # 하루 활동 시작 09:00
DAY_END = 21 * 60           # 하루 활동 종료 21:00
DAY = DAY_END - DAY_START   # 720분 = 하루 예산
HOP = 45                    # 시군을 넘어갈 때 더하는 환승 여유(발권·대기)
DETOUR = 1.35               # 직선거리 → 도로거리 (대중교통·도보)
DETOUR_CAR = 1.30           # 직선거리 → 도로거리 (자가용)
LEG_MIN_FLOOR = 8           # 어떤 구간도 이보다 짧게 잡지 않는다

_HOURS_RE = re.compile(r"(\d{1,2}):(\d{2})\s*[–~\-]\s*(\d{1,2}):(\d{2})")


def stay_min(place):
    """권장 체류 분. 없으면 0 — 0인 장소는 코스에 넣지 않는다(숙소 등)."""
    return place.get("stayMin") or 0


def fmt_stay(minutes):
    """'1h 30m' 꼴 표기."""
    if not minutes:
        return "0m"
    if minutes < 60:
        return f"{minutes}m"
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m" if m else f"{h}h"


def open_hours(place):
    """운영시간 문자열 → (개장분, 폐장분). 'HH:MM–HH:MM' 이 없으면 None(상시 개방).

    폐장이 개장보다 이르면 자정을 넘긴 것으로 보고 24시간을 더한다.
    """
    m = _HOURS_RE.search(str(place.get("hours") or ""))
    if not m:
        return None
    o = int(m.group(1)) * 60 + int(m.group(2))
    c = int(m.group(3)) * 60 + int(m.group(4))
    if c <= o:
        c += 24 * 60
    return o, c


# ── 거리·이동시간 ────────────────────────────────────────────────────────
def straight_km(p, q):
    """두 좌표의 직선거리(km). 위도 보정 등거리 근사."""
    R = 6371
    d_la = math.radians(q["lat"] - p["lat"])
    d_lo = math.radians(q["lng"] - p["lng"])
    la = math.radians((p["lat"] + q["lat"]) / 2)
    return R * math.hypot(d_la, d_lo * math.cos(la))


def own_drive_min(a, b):
    """자가용 주행 시간. 한국도로공사 고속도로 표정속도(약 92km/h) 모델.

    20km 이내는 시내도로 35km/h, 그 이상은 진출입 15분 + 시내 20km + 고속도로.
    2시간마다 휴게소 15분을 더한다.
    """
    d = straight_km(a, b) * DETOUR_CAR
    if d <= 20:
        return max(LEG_MIN_FLOOR, round(d / 35 * 60))
    run = 15 + (20 / 35 * 60) + ((d - 20) / 92 * 60)
    rest = math.floor(run / 120) * 15
    return round(run + rest)


def leg_info(p, q, mode="transit", hubs=None, metro_cities=None):
    """두 장소 사이 이동시간·거리.

    mode: transit(대중교통) · driving(렌터카) · own(자가용)

    시군(region)이 다른 **광역 구간**은 시내 모델 대신 KTX·고속버스 계수를 쓴다.
    구글 대중교통이 시내버스 우회 경로를 돌려줘 8시간대가 나오는 문제를 피하기
    위한 규칙이다.
    """
    hubs = hubs or {}
    metro_cities = metro_cities or {}
    pr, qr = p.get("region"), q.get("region")
    wide = bool(pr and qr and pr != qr)
    d = straight_km(p, q) * DETOUR

    if mode == "own":
        return {"km": round(d, 2), "min": own_drive_min(p, q),
                "wide": wide, "own": True}

    if wide:
        ha = (hubs.get(pr) or {}).get("modes", ["bus"])
        hb = (hubs.get(qr) or {}).get("modes", ["bus"])
        metro = bool(metro_cities.get(pr) and metro_cities.get(qr))
        rail = any(x in ha and x in hb for x in ("ktx", "srt"))
        if metro:                       # 전철권 내부는 환승 여유를 짧게
            minutes = (12 + d * 0.95) + 15
        elif rail:                      # 고속철 200km/h + 발권·대기 35분
            minutes = (18 + d * 0.30) + 35
        else:                           # 고속버스 110km/h + 발권·대기 35분
            minutes = (18 + d * 0.55) + 35
    elif mode == "transit":
        # 도보권 11분/km, 그 밖은 대기 15분 + 3.6분/km
        minutes = max(10, d * 11) if d <= 3 else 15 + d * 3.6
    else:                               # 렌터카
        minutes = 8 + d * 2.2 if d <= 30 else 20 + d * 1.05

    return {"km": round(d, 2), "min": max(LEG_MIN_FLOOR, round(minutes)),
            "wide": wide}


def access_min(origin, hub, mode):
    """출발지(역·터미널·공항) → 지역 관문까지의 광역 접근 시간."""
    if not origin or not hub:
        return 0
    to = hub if (hub.get("lat") and hub.get("lng")) else origin
    if mode == "own":
        return own_drive_min(origin, to)
    d = straight_km(origin, to) * DETOUR
    if mode == "air":
        return round(90 + d * 0.11)     # 수속·탑승 대기 + 순항
    if mode == "ship":
        return round(60 + d * 0.85)     # 승선 수속 + 약 40km/h
    if mode == "metro":
        return round(12 + d * 0.95)     # 광역전철 약 63km/h
    if mode in ("ktx", "srt"):
        return round(18 + d * 0.30)     # 고속선 약 200km/h
    return round(18 + d * 0.55)         # 고속버스 약 110km/h


# ── 일자 창 ──────────────────────────────────────────────────────────────
def _to_min(t):
    h, m = str(t).split(":")
    return int(h) * 60 + int(m)


def day_windows(days=1, dep_time="08:00", ret_time="19:00", acc_in=0,
                has_trip=True):
    """날짜별 활동 가능 분. 결과는 항상 0~720 사이다.

    중간일 720분, 첫날은 21:00 − (출발 + 광역 이동), 마지막날은 여행지 출발 − 09:00.
    1일 여행이면 첫날·마지막날 규칙이 함께 적용된다.
    """
    if not has_trip:
        return [DAY]
    dep, ret = _to_min(dep_time), _to_min(ret_time)
    out = []
    for i in range(days):
        avail = DAY
        if i == 0:
            avail = max(0, min(DAY, DAY_END - (dep + acc_in)))
        if i == days - 1:
            avail = min(avail, max(0, min(DAY, ret - DAY_START)))
        out.append(avail)
    return out


def day_start_clock(day_idx, dep_time="08:00", acc_in=0, has_trip=True):
    """첫날은 출발+접근이 09:00 을 넘기면 그 시각부터, 나머지 날은 09:00 부터."""
    if not has_trip or day_idx != 0:
        return DAY_START
    return max(DAY_START, _to_min(dep_time) + acc_in)


# ── 일자 배정과 시계 ─────────────────────────────────────────────────────
def assign_days(items, windows, leg_fn):
    """코스 순서 그대로 (이동 + 체류) 를 일자 창에 담는다.

    창을 넘기면 다음 날로 넘어가고, 마지막 날에도 안 들어가는 경유지는 잘라낸다.
    돌려주는 값: (일자별 인덱스 목록, 담긴 경유지 수)
    """
    days = len(windows)
    buckets = [[] for _ in range(days)]
    d = used = keep = 0
    for i, item in enumerate(items):
        leg_in = leg_fn(items[i - 1], item)["min"] if i > 0 else 0
        stay = stay_min(item)
        placed = False
        while d < days:
            if used + leg_in + stay <= windows[d]:
                used += leg_in + stay
                placed = True
                break
            if d == days - 1:
                break
            d += 1
            used = 0
        if not placed:
            break                        # 뒤는 전부 못 들어간다
        buckets[d].append(i)
        keep += 1
    return buckets, keep


def _hm(t):
    return f"{(t // 60) % 24:02d}:{t % 60:02d}"


def timeline(items, buckets, leg_fn, dep_time="08:00", acc_in=0,
             has_trip=True):
    """일자별 경유지에 도착·출발 시각을 붙인다.

    그날 시작 시각에서 출발해 이동시간을 더하고, 개장 전이면 개장까지 기다린 뒤
    체류시간만큼 머문다. 폐장은 여기서 강제하지 않고 `closesBefore` 로 알린다 —
    앱이 그렇게 동작한다.
    """
    out = []
    for day, idxs in enumerate(buckets):
        clk = day_start_clock(day, dep_time, acc_in, has_trip)
        for k, idx in enumerate(idxs):
            p = items[idx]
            move = leg_fn(items[idxs[k - 1]], p)["min"] if k > 0 else 0
            clk += move
            oh = open_hours(p)
            wait = 0
            if oh and clk < oh[0]:
                wait = oh[0] - clk
                clk = oh[0]
            at = clk
            stay = stay_min(p)
            clk += stay
            out.append({
                "day": day + 1, "order": k + 1,
                "placeId": p.get("placeId") or p.get("id"),
                "nameKo": p.get("nameKo"),
                "cat": p.get("catFinal") or p.get("catApp"),
                "moveMin": move, "waitMin": wait, "stayMin": stay,
                "arrive": _hm(at), "leave": _hm(clk),
                "arriveMin": at, "leaveMin": clk,
                "closesBefore": bool(oh and clk > oh[1]),
            })
    return out
