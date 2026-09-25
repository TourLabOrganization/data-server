# -*- coding: utf-8 -*-
"""앱 장소 1,171곳을 TourAPI 공식 분류체계로 재분류한다.

    python -m pipeline.tourapi

앱의 카테고리(heal·herit·activity·food·sea·stay)는 손으로 넣은 값이라 지역별로
기준이 다르다. 제주·부산의 해변이 sea 가 아니라 heal 로 들어가 있는 식이다.
이 카테고리로 테마 강도를 계산하고 있어서 결과가 왜곡된다.

한국관광공사 TourAPI 의 분류체계(lclsSystm1/2/3)를 기준으로 다시 매긴다.
데이터랩 '인기관광지'의 분류 컬럼도 같은 체계라서, 재분류하면 앱과 데이터랩이
같은 축 위에 놓인다 (docs/datalab.md).

이 스크립트는 판정을 덮어쓰지 않는다. 검토용 표를 낼 뿐이다.
산출: data/derived/categories.json, reports/reclassify.md
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from .common import CACHE, DERIVED, NFC, REPORTS, norm_name
from .places import extract

KEY = os.environ.get("TOURAPI_KEY", "")
ENDPOINT = "https://apis.data.go.kr/B551011/KorService2/searchKeyword2"

# 장소가 아닌 콘텐츠. 추천코스(25)와 축제·행사(15)는 좌표가 있어도 '장소'가 아니다.
# 파일럿에서 '해인사'가 '해인사와 팔만대장경을 만나는 여행'(코스)에 걸렸다.
SKIP_CONTENT_TYPES = {"15", "25"}

MAX_DIST_KM = 3.0        # 이보다 멀면 동명이인으로 보고 버린다
MIN_SIMILARITY = 0.40    # 이름이 이만큼도 안 닮으면 버린다

# 좌표 기반 폴백은 주변 식당까지 다 끌어오므로 이름을 더 엄하게 본다.
LOC_RADIUS_M = 1000
LOC_MIN_SIMILARITY = 0.60
LOC_ENDPOINT = "https://apis.data.go.kr/B551011/KorService2/locationBasedList2"


# ── TourAPI 분류 → 앱 카테고리 ────────────────────────────────────────────
# 중분류(lclsSystm2) 기준. 소분류로 갈라야 하는 것만 아래 OVERRIDE 에 둔다.
# None 은 '앱이 다루지 않는 대상'(쇼핑시설·교통시설·축제)이라는 뜻이다.
CAT_BY_MID = {
    # 숙박
    "AC01": "stay", "AC02": "stay", "AC03": "stay", "AC04": "stay",
    "AC05": "stay", "AC06": "stay",
    # 체험관광 — 앱의 heal 은 '힐링·생태·체험'이라 웰니스·산사체험이 여기 붙는다
    "EX01": "activity", "EX02": "activity", "EX03": "activity",
    "EX04": "heal", "EX05": "heal", "EX06": "activity", "EX07": "activity",
    # 음식
    "FD01": "food", "FD02": "food", "FD03": "food", "FD04": "food",
    "FD05": "food",
    # 역사관광
    "HS01": "herit", "HS02": "herit", "HS03": "herit", "HS04": "herit",
    # 레저스포츠
    "LS01": "activity", "LS02": "sea", "LS03": "activity", "LS04": "activity",
    # 자연관광 — NA02 는 강·호수와 해변이 섞여 있어 소분류로 가른다
    "NA01": "heal", "NA02": "heal", "NA03": "heal", "NA04": "heal",
    "NA05": "heal",
    # 쇼핑 — 앱에는 쇼핑 카테고리가 없다. 시장만 food 로 받는다
    "SH01": None, "SH02": None, "SH03": None, "SH04": None,
    "SH05": "activity", "SH06": "food", "SH07": None,
    # 문화관광
    "VE01": "activity", "VE02": "activity", "VE03": "heal", "VE04": "herit",
    "VE05": "activity", "VE06": "activity", "VE07": "herit", "VE08": "activity",
    "VE09": "herit", "VE10": "activity", "VE11": None, "VE12": "activity",
}

# 소분류(lclsSystm3)가 중분류와 다른 판정을 내려야 하는 경우.
# 바다 관련이 핵심이다 — 앱의 sea 는 TourAPI 대분류에 대응물이 없고,
# NA02(하천‧해양)와 VE01(랜드마크) 안에 흩어져 있다.
CAT_BY_SUB = {
    "NA020100": "heal",   # 강
    "NA020200": "heal",   # 호수
    "NA020300": "heal",   # 저수지
    "NA020400": "heal",   # 연못·늪
    "NA020500": "sea",    # 섬
    "NA020600": "sea",    # 염전
    "NA020700": "sea",    # 항구/포구
    "NA020800": "sea",    # 해안절경
    "NA020900": "sea",    # 해변. 해수욕장
    "VE010800": "sea",    # 등대
    "VE010700": "heal",   # 댐
}


def to_app_cat(m2, m3):
    """TourAPI 중·소분류 → 앱 카테고리. 소분류가 있으면 그쪽을 우선한다."""
    if m3 in CAT_BY_SUB:
        return CAT_BY_SUB[m3]
    return CAT_BY_MID.get(m2, None)


# ── 조회 ─────────────────────────────────────────────────────────────────
def _region_names(places):
    """장소 데이터에 실제로 나오는 지역명 109종. 접두사 제거에 쓴다.

    '부산어린이대공원'처럼 띄어쓰기 없이 지역명이 붙은 이름이 많은데,
    TourAPI 는 '부산 어린이대공원'으로 띄어 놓아서 그대로는 안 걸린다.
    """
    return sorted({p["region"] for p in places if p["region"] and len(p["region"]) >= 2},
                  key=len, reverse=True)


def keyword_candidates(name, regions=()):
    """검색어 후보를 넓은 것부터 좁은 것 순으로. 첫 번째로 결과가 나오면 쓴다.

    파일럿에서 실패한 것들이 대부분 지역 접두사 때문이었다.
    '고성 통일전망대' → '통일전망대', '팔공산 동화사' → '동화사'.
    """
    n = NFC(name)
    out = [n]
    # '·' 로 묶인 복합 장소는 앞쪽만 ('송도해수욕장 · 케이블카' → '송도해수욕장')
    for sep in ("·", "・", "&"):
        if sep in n:
            out.append(n.split(sep)[0].strip())
    tokens = n.replace("·", " ").split()
    if len(tokens) > 1:
        out.append(tokens[-1])            # 마지막 어절 ('팔공산 동화사' → '동화사')
        out.append(" ".join(tokens[1:]))  # 첫 어절만 뗀 것
    # 띄어쓰기 없이 붙은 지역 접두사 ('부산어린이대공원' → '어린이대공원')
    for reg in regions:
        if n.startswith(reg) and len(n) > len(reg) + 2:
            out.append(n[len(reg):].strip())
            break
    seen, uniq = set(), []
    for k in out:
        k = k.strip()
        if len(k) >= 2 and k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq[:5]


def api_nearby(lng, lat):
    """좌표 기반 조회. 이름으로 못 찾은 장소의 마지막 그물이다.

    '동피랑벽화마을'(앱)은 TourAPI 에 '동피랑마을'로 있어서 이름 검색이 0건인데,
    좌표로는 33m 거리에서 잡힌다. 다만 주변 식당·카페도 같이 나오므로
    이름 유사도를 더 엄하게 걸어야 한다.
    """
    cache_dir = os.path.join(CACHE, "tourapi_loc")
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{lng:.5f}_{lat:.5f}.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))

    q = urllib.parse.urlencode({
        "serviceKey": KEY, "MobileOS": "ETC", "MobileApp": "TourNavigator",
        "_type": "json", "mapX": f"{lng:.6f}", "mapY": f"{lat:.6f}",
        "radius": LOC_RADIUS_M, "numOfRows": 30, "pageNo": 1, "arrange": "E",
    })
    items = []
    for attempt in range(3):
        try:
            with urllib.request.urlopen(LOC_ENDPOINT + "?" + q, timeout=25) as r:
                body = json.load(r)["response"]["body"]
            it = body.get("items")
            if it:
                it = it["item"]
                items = it if isinstance(it, list) else [it]
            break
        except Exception:
            if attempt == 2:
                return None
            time.sleep(1.5)
    json.dump(items, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return items


def api_search(keyword):
    """searchKeyword2 호출. 응답은 캐싱해서 중간에 끊겨도 이어받는다."""
    cache_dir = os.path.join(CACHE, "tourapi")
    os.makedirs(cache_dir, exist_ok=True)
    safe = urllib.parse.quote(keyword, safe="")[:120]
    path = os.path.join(cache_dir, f"{safe}.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))

    q = urllib.parse.urlencode({
        "serviceKey": KEY, "MobileOS": "ETC", "MobileApp": "TourNavigator",
        "_type": "json", "keyword": keyword, "numOfRows": 20, "pageNo": 1,
    })
    items = []
    for attempt in range(3):
        try:
            with urllib.request.urlopen(ENDPOINT + "?" + q, timeout=25) as r:
                body = json.load(r)["response"]["body"]
            it = body.get("items")
            if it:
                it = it["item"]
                items = it if isinstance(it, list) else [it]
            break
        except Exception:
            if attempt == 2:
                return None               # 캐시하지 않는다. 다음 실행에서 재시도
            time.sleep(1.5)
    json.dump(items, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return items


def dist_km(lng1, lat1, lng2, lat2):
    """근사 거리. 한반도 위도대에서 이 정도면 충분하다."""
    return (((lng1 - lng2) * 88.9) ** 2 + ((lat1 - lat2) * 111.0) ** 2) ** .5


def best_candidate(place, items):
    """이름 유사도와 거리를 함께 보고 고른다.

    거리만 보면 틀린다. 파일럿에서 '범어사'가 190m 떨어진 '범어사 성보박물관'에,
    '온양온천'이 '온양온천시장'에 걸렸다. 둘 다 분류가 완전히 달라진다.
    """
    want = norm_name(place["nameKo"])
    best = None
    for i in items or []:
        if str(i.get("contenttypeid")) in SKIP_CONTENT_TYPES:
            continue
        try:
            mx, my = float(i["mapx"]), float(i["mapy"])
        except (KeyError, TypeError, ValueError):
            continue
        if not mx or not my:
            continue
        d = dist_km(mx, my, place["lng"], place["lat"])
        if d > MAX_DIST_KM:
            continue
        sim = SequenceMatcher(None, want, norm_name(i.get("title", ""))).ratio()
        if sim < MIN_SIMILARITY:
            continue
        score = sim - min(d, MAX_DIST_KM) * 0.08
        if best is None or score > best[0]:
            best = (score, sim, d, i)
    return best


def confidence(sim, d):
    if sim >= 0.85 and d <= 1.0:
        return "high"
    if sim >= 0.60 and d <= 2.0:
        return "medium"
    return "low"


# ── 본체 ─────────────────────────────────────────────────────────────────
def classify(places, progress_every=100):
    results, misses = [], 0
    regions = _region_names(places)
    for n, p in enumerate(places, 1):
        if p["lat"] is None or p["lng"] is None:
            results.append({**_blank(p), "note": "좌표 없음"})
            continue
        hit = None
        for kw in keyword_candidates(p["nameKo"], regions):
            items = api_search(kw)
            if items is None:               # 호출 실패
                results.append({**_blank(p), "note": "조회 실패"})
                hit = "FAIL"
                break
            cand = best_candidate(p, items)
            if cand:
                hit = cand
                break
            time.sleep(0.05)
        if hit == "FAIL":
            continue
        if not hit:                         # 이름으로 못 찾았으면 좌표로 한 번 더
            near = api_nearby(p["lng"], p["lat"])
            if near:
                cand = best_candidate(p, near)
                if cand and cand[1] >= LOC_MIN_SIMILARITY:
                    hit = cand
        if not hit:
            misses += 1
            results.append({**_blank(p), "note": "TourAPI 미매칭"})
            continue
        _, sim, d, item = hit
        m1 = item.get("lclsSystm1") or ""
        m2 = item.get("lclsSystm2") or ""
        m3 = item.get("lclsSystm3") or ""
        results.append({
            **_blank(p),
            "catOfficial": to_app_cat(m2, m3),
            "lclsSystm1": m1, "lclsSystm2": m2, "lclsSystm3": m3,
            "contentTypeId": str(item.get("contenttypeid") or ""),
            "tourapiTitle": NFC(item.get("title") or ""),
            "similarity": round(sim, 3),
            "distanceKm": round(d, 3),
            "confidence": confidence(sim, d),
        })
        if n % progress_every == 0:
            print(f"  {n}/{len(places)} 조회… (미매칭 {misses})", flush=True)
    return results


def _blank(p):
    return {"id": p["id"], "nameKo": p["nameKo"], "region": p["region"],
            "catApp": p["catApp"], "catOfficial": None, "lclsSystm1": "",
            "lclsSystm2": "", "lclsSystm3": "", "contentTypeId": "",
            "tourapiTitle": "", "similarity": None, "distanceKm": None,
            "confidence": None, "note": ""}


def write_report(rows, codes):
    name2 = {k2: v2["name"] for v in codes.values()
             for k2, v2 in v["children"].items()}
    name3 = {k3: n3 for v in codes.values() for v2 in v["children"].values()
             for k3, n3 in v2["children"].items()}

    matched = [r for r in rows if r["catOfficial"]]
    changed = [r for r in matched if r["catOfficial"] != r["catApp"]]
    same = [r for r in matched if r["catOfficial"] == r["catApp"]]
    out_of_scope = [r for r in rows if r["lclsSystm2"] and not r["catOfficial"]]
    unmatched = [r for r in rows if r["note"]]

    L = []
    L.append("# TourAPI 재분류 결과\n")
    L.append(f"앱 장소 **{len(rows)}곳**을 한국관광공사 TourAPI 분류체계"
             f"(`lclsSystm1/2/3`)로 다시 매겼다.\n")
    L.append("| | 곳 | 비율 |")
    L.append("|---|---:|---:|")
    L.append(f"| 조회 성공 | {len(matched) + len(out_of_scope)} | "
             f"{(len(matched)+len(out_of_scope))/len(rows)*100:.0f}% |")
    L.append(f"| └ 앱과 분류 일치 | {len(same)} | "
             f"{len(same)/len(rows)*100:.0f}% |")
    L.append(f"| └ **분류 변경 대상** | **{len(changed)}** | "
             f"{len(changed)/len(rows)*100:.0f}% |")
    L.append(f"| └ 앱 대상 아님(쇼핑·교통) | {len(out_of_scope)} | "
             f"{len(out_of_scope)/len(rows)*100:.0f}% |")
    L.append(f"| 미매칭 | {len(unmatched)} | "
             f"{len(unmatched)/len(rows)*100:.0f}% |\n")

    flow = Counter((r["catApp"], r["catOfficial"]) for r in changed)
    L.append("## 어떤 변경이 일어나는가\n")
    L.append("| 앱 분류 | → TourAPI 분류 | 곳 |")
    L.append("|---|---|---:|")
    for (a, b), c in flow.most_common():
        L.append(f"| `{a}` | `{b}` | {c} |")
    L.append("")

    L.append("## 신뢰도별\n")
    conf = Counter(r["confidence"] for r in changed)
    L.append("| 신뢰도 | 곳 | 기준 |")
    L.append("|---|---:|---|")
    L.append(f"| high | {conf.get('high', 0)} | 이름 유사도 ≥0.85, 거리 ≤1km |")
    L.append(f"| medium | {conf.get('medium', 0)} | 유사도 ≥0.60, 거리 ≤2km |")
    L.append(f"| low | {conf.get('low', 0)} | 그 외 — **눈으로 확인 필요** |\n")

    sea = [r for r in changed if r["catOfficial"] == "sea"]
    if sea:
        L.append(f"## 바다로 재분류되는 {len(sea)}곳\n")
        L.append("앱에서 `sea` 가 아니었지만 TourAPI 가 해변·항구·섬으로 분류한 곳이다.\n")
        L.append("| 지역 | 장소 | 앱 | TourAPI 소분류 | 신뢰도 |")
        L.append("|---|---|---|---|---|")
        for r in sorted(sea, key=lambda x: (x["region"] or "", x["nameKo"])):
            L.append(f"| {r['region'] or '—'} | {r['nameKo']} | `{r['catApp']}` | "
                     f"{name3.get(r['lclsSystm3'], r['lclsSystm2'])} | {r['confidence']} |")
        L.append("")

    L.append("## 신뢰도 low — 사람이 봐야 하는 변경\n")
    low = [r for r in changed if r["confidence"] == "low"]
    if low:
        L.append("| 장소 | 앱 | → | TourAPI가 매칭한 이름 | 유사도 | 거리 |")
        L.append("|---|---|---|---|---:|---:|")
        for r in sorted(low, key=lambda x: x["similarity"] or 0)[:60]:
            L.append(f"| {r['nameKo']} | `{r['catApp']}` | `{r['catOfficial']}` | "
                     f"{r['tourapiTitle']} | {r['similarity']} | {r['distanceKm']}km |")
    else:
        L.append("없음.")
    L.append("")

    L.append("## 미매칭\n")
    L.append(f"{len(unmatched)}곳. TourAPI 에 없거나 이름이 너무 다른 경우다. "
             f"앱 분류를 그대로 둔다.\n")
    for r in unmatched[:40]:
        L.append(f"- {r['nameKo']} ({r['region'] or '—'}) — {r['note']}")
    if len(unmatched) > 40:
        L.append(f"- … 외 {len(unmatched) - 40}곳")
    L.append("")

    os.makedirs(REPORTS, exist_ok=True)
    dst = os.path.join(REPORTS, "reclassify.md")
    open(dst, "w", encoding="utf-8").write("\n".join(L))
    return dst, dict(total=len(rows), matched=len(matched), same=len(same),
                     changed=len(changed), out_of_scope=len(out_of_scope),
                     unmatched=len(unmatched), sea=len(sea))


def main():
    if not KEY:
        sys.exit("TOURAPI_KEY 가 없습니다. .env 에 공공데이터포털 서비스키를 넣어 주세요.\n"
                 "(키 없이도 나머지 파이프라인은 정상 동작합니다.)")
    codes_path = os.path.join(os.path.dirname(DERIVED), "mapping",
                              "tourapi_codes.json")
    codes = json.load(open(codes_path, encoding="utf-8"))

    places = extract()
    print(f"앱 장소 {len(places)}곳을 TourAPI 로 조회합니다. "
          f"(캐시: {os.path.join(CACHE, 'tourapi')})")
    rows = classify(places)

    os.makedirs(DERIVED, exist_ok=True)
    dst = os.path.join(DERIVED, "categories.json")
    json.dump({"count": len(rows), "places": rows},
              open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    report, s = write_report(rows, codes)
    print(f"\n조회 성공 {s['matched'] + s['out_of_scope']}곳 "
          f"/ 미매칭 {s['unmatched']}곳")
    print(f"  분류 일치      {s['same']}곳")
    print(f"  분류 변경 대상  {s['changed']}곳  (그중 바다로 {s['sea']}곳)")
    print(f"  앱 대상 아님    {s['out_of_scope']}곳")
    print(f"\n완료 → {dst}\n       {report}")


if __name__ == "__main__":
    main()
