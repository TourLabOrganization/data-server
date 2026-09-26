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
import urllib.error
import urllib.parse
import urllib.request
import re
from collections import Counter
from difflib import SequenceMatcher

from .common import CACHE, DERIVED, NFC, REPORTS, norm_name
from .taxonomy import to_app_cat
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


class QuotaExceeded(Exception):
    """공공데이터포털 일일 호출 한도 초과.

    개발계정은 하루 1,000회다. 장소 1,171곳에 검색어를 여러 개 시도하므로
    한 번에 다 돌지 못한다. 한도에 걸리면 재시도해도 소용없으니 즉시 멈추고,
    캐시된 것까지는 저장한 뒤 다음 날 이어받는다.
    """


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
                raw = r.read().decode("utf-8", "replace")
            if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in raw:
                raise QuotaExceeded()
            body = json.loads(raw)["response"]["body"]
            it = body.get("items")
            if it:
                it = it["item"]
                items = it if isinstance(it, list) else [it]
            break
        except QuotaExceeded:
            raise
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise QuotaExceeded()
            if attempt == 2:
                return None
            time.sleep(1.5)
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
                raw = r.read().decode("utf-8", "replace")
            if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in raw:
                raise QuotaExceeded()
            body = json.loads(raw)["response"]["body"]
            it = body.get("items")
            if it:
                it = it["item"]
                items = it if isinstance(it, list) else [it]
            break
        except QuotaExceeded:
            raise
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise QuotaExceeded()
            if attempt == 2:
                return None               # 캐시하지 않는다. 다음 실행에서 재시도
            time.sleep(1.5)
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


# 해변은 길어서 TourAPI 좌표와 앱 좌표가 1~2km 떨어지는 일이 흔하다. 그래서
# 일반 신뢰도 기준(거리 ≤1km)에 걸려 멀쩡한 해변이 보류됐다(김녕·중문색달·하도 등).
#
# 이 조합에서는 거리를 안 봐도 안전하다 — 앱 이름에 '해수욕장/해변'이 있고 TourAPI 가
# NA0209(해변·해수욕장)로 분류했다면, 설령 옆 해변에 잘못 붙었더라도 **분류는 sea 로
# 같다.** 장소를 틀려도 답이 맞는 드문 경우다.
BEACH_NAME = re.compile(r"해수욕장|해변")
BEACH_SUB = "NA0209"
BEACH_MIN_SIM = 0.70


def _beach_override(row):
    return (row["catOfficial"] == "sea"
            and row["lclsSystm3"].startswith(BEACH_SUB)
            and BEACH_NAME.search(NFC(row["nameKo"]))
            and (row["similarity"] or 0) >= BEACH_MIN_SIM)


def apply_decision(row):
    """이 변경을 앱에 그대로 반영해도 되는가. (적용여부, 사유)

    분류 자체(catOfficial)는 TourAPI 판정을 그대로 남긴다. 여기서 정하는 것은
    **앱에 반영할지**뿐이다. 둘을 섞으면 나중에 판단 근거를 못 되짚는다.
    """
    if not row["catOfficial"] or row["catOfficial"] == row["catApp"]:
        return False, ""
    if row["confidence"] != "high" and not _beach_override(row):
        return False, "신뢰도 부족 — 사람이 확인"
    # 관광지가 옆 숙박시설에 걸리는 일이 잦다(용봉산→용봉산캠핑장,
    # 합천호→합천호 스마일펜션). stay 로 바꾸면 추천에서 통째로 빠지므로,
    # 앱이 이미 stay 로 본 곳이 아니면 반영하지 않는다.
    if row["catOfficial"] == "stay":
        return False, "숙박시설 오매칭 위험"
    # 먹자골목(황리단길·명동 닭갈비골목)을 TourAPI 는 VE04(문화거리)로 본다.
    # 형태를 본 분류이고, 앱의 food 는 목적을 본 분류다. 여행 앱에서는 후자가
    # 쓸모 있으므로 앱 값을 지킨다.
    if (row["catApp"] == "food" and row["catOfficial"] == "herit"
            and row["lclsSystm2"] == "VE04"):
        return False, "먹자골목 — 앱의 food 가 더 적절"
    return True, ""


def confidence(sim, d):
    if sim >= 0.85 and d <= 1.0:
        return "high"
    if sim >= 0.60 and d <= 2.0:
        return "medium"
    return "low"


# ── 본체 ─────────────────────────────────────────────────────────────────
def classify(places, progress_every=100):
    """전부 조회한다. 한도에 걸리면 거기까지의 결과와 중단 여부를 함께 돌려준다."""
    results, misses = [], 0
    regions = _region_names(places)
    for n, p in enumerate(places, 1):
        try:
            results.append(_classify_one(p, regions))
        except QuotaExceeded:
            done = len(results)
            print(f"\n  일일 호출 한도 초과 — {done}/{len(places)}곳에서 중단합니다.",
                  flush=True)
            print("  받아둔 응답은 캐시에 남아 있습니다. 한도가 풀린 뒤 다시 돌리면"
                  " 캐시부터 소진하고 그 다음부터 이어서 조회합니다.", flush=True)
            for rest in places[done:]:
                results.append({**_blank(rest), "note": "호출 한도로 미조회"})
            return results, True
        if results[-1]["note"] == "TourAPI 미매칭":
            misses += 1
        if n % progress_every == 0:
            print(f"  {n}/{len(places)} 조회… (미매칭 {misses})", flush=True)
    return results, False


def _classify_one(p, regions):
    """장소 하나를 분류한다. 한도 초과는 QuotaExceeded 로 위에 던진다."""
    if p["lat"] is None or p["lng"] is None:
        return {**_blank(p), "note": "좌표 없음"}

    hit = None
    for kw in keyword_candidates(p["nameKo"], regions):
        items = api_search(kw)
        if items is None:                   # 재시도까지 실패
            return {**_blank(p), "note": "조회 실패"}
        cand = best_candidate(p, items)
        if cand:
            hit = cand
            break
        time.sleep(0.05)

    if not hit:                             # 이름으로 못 찾았으면 좌표로 한 번 더
        near = api_nearby(p["lng"], p["lat"])
        if near:
            cand = best_candidate(p, near)
            if cand and cand[1] >= LOC_MIN_SIMILARITY:
                hit = cand
    if not hit:
        return {**_blank(p), "note": "TourAPI 미매칭"}

    _, sim, d, item = hit
    m2 = item.get("lclsSystm2") or ""
    m3 = item.get("lclsSystm3") or ""
    return {
        **_blank(p),
        "catOfficial": to_app_cat(m2, m3),
        "lclsSystm1": item.get("lclsSystm1") or "",
        "lclsSystm2": m2, "lclsSystm3": m3,
        "contentTypeId": str(item.get("contenttypeid") or ""),
        "tourapiTitle": NFC(item.get("title") or ""),
        "similarity": round(sim, 3),
        "distanceKm": round(d, 3),
        "confidence": confidence(sim, d),
    }


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
    L.append(f"| 미매칭·미조회 | {len(unmatched)} | "
             f"{len(unmatched)/len(rows)*100:.0f}% |\n")
    pending = [r for r in unmatched if r["note"] == "호출 한도로 미조회"]
    if pending:
        L.append(f"> ⚠️ 이 실행은 공공데이터포털 일일 호출 한도로 중간에 멈췄다. "
                 f"**{len(pending)}곳은 아직 조회하지 못했다.** 한도가 풀린 뒤 다시 "
                 f"돌리면 캐시된 응답부터 소진하고 그 다음부터 이어서 조회한다.\n")

    flow = Counter((r["catApp"], r["catOfficial"]) for r in changed)
    L.append("## 어떤 변경이 일어나는가\n")
    L.append("| 앱 분류 | → TourAPI 분류 | 곳 |")
    L.append("|---|---|---:|")
    for (a, b), c in flow.most_common():
        L.append(f"| `{a}` | `{b}` | {c} |")
    L.append("")

    L.append("## 신뢰도별\n")
    applied = [r for r in changed if r.get("apply")]
    held = Counter(r.get("applyNote") for r in changed if not r.get("apply"))
    L.append("## 앱에 반영할 것 / 보류할 것\n")
    L.append(f"변경 대상 {len(changed)}곳 중 **{len(applied)}곳을 앱에 반영**하고, "
             f"{len(changed) - len(applied)}곳은 보류한다.\n")
    L.append("| 판정 | 곳 |")
    L.append("|---|---:|")
    L.append(f"| **반영** | {len(applied)} |")
    for note, c in held.most_common():
        L.append(f"| 보류 — {note} | {c} |")
    L.append("")

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
                     unmatched=len(unmatched), sea=len(sea),
                     applied=len(applied))


def redecide():
    """이미 조회해 둔 categories.json 에 **적용 판정만 다시** 매긴다.

    API 를 한 번도 부르지 않는다. 판정 규칙(apply_decision)만 고쳤을 때 쓴다 —
    전체 재조회는 일일 한도에 걸려 결과가 부분으로 덮일 위험이 있다. 실제로
    그렇게 168곳이 115곳으로 줄어든 적이 있다.
    """
    codes_path = os.path.join(os.path.dirname(DERIVED), "mapping",
                              "tourapi_codes.json")
    codes = json.load(open(codes_path, encoding="utf-8"))
    dst = os.path.join(DERIVED, "categories.json")
    if not os.path.exists(dst):
        sys.exit(f"{dst} 가 없습니다. 먼저 전체 조회를 한 번 돌려야 합니다.")
    rows = json.load(open(dst, encoding="utf-8"))["places"]

    before = sum(1 for r in rows if r.get("apply"))
    for r in rows:
        r["apply"], r["applyNote"] = apply_decision(r)
    after = sum(1 for r in rows if r.get("apply"))

    json.dump({"count": len(rows), "places": rows},
              open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    report, _ = write_report(rows, codes)
    print(f"판정만 다시 매겼습니다 (API 호출 없음)")
    print(f"  앱 반영 {before}곳 → {after}곳")
    print(f"\n완료 → {dst}\n       {report}")


def main():
    if "--redecide" in sys.argv:
        return redecide()
    if not KEY:
        sys.exit("TOURAPI_KEY 가 없습니다. .env 에 공공데이터포털 서비스키를 넣어 주세요.\n"
                 "(키 없이도 나머지 파이프라인은 정상 동작합니다.)")
    codes_path = os.path.join(os.path.dirname(DERIVED), "mapping",
                              "tourapi_codes.json")
    codes = json.load(open(codes_path, encoding="utf-8"))

    places = extract()
    print(f"앱 장소 {len(places)}곳을 TourAPI 로 조회합니다. "
          f"(캐시: {os.path.join(CACHE, 'tourapi')})")
    rows, stopped = classify(places)

    for r in rows:
        r["apply"], r["applyNote"] = apply_decision(r)

    os.makedirs(DERIVED, exist_ok=True)
    dst = os.path.join(DERIVED, "categories.json")
    json.dump({"count": len(rows), "places": rows},
              open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    report, s = write_report(rows, codes)
    if stopped:
        print("\n  ⚠️ 일일 호출 한도로 중간에 멈췄습니다. 아래 수치는 조회된 부분만"
              " 반영한 것입니다.")
    print(f"\n조회 성공 {s['matched'] + s['out_of_scope']}곳 "
          f"/ 미매칭 {s['unmatched']}곳")
    print(f"  분류 일치      {s['same']}곳")
    print(f"  분류 변경 대상  {s['changed']}곳  (그중 바다로 {s['sea']}곳)")
    print(f"     └ 앱 반영 {s['applied']}곳 / 보류 {s['changed'] - s['applied']}곳")
    print(f"  앱 대상 아님    {s['out_of_scope']}곳")
    print(f"\n완료 → {dst}\n       {report}")


if __name__ == "__main__":
    main()
