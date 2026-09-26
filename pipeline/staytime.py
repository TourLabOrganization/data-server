# -*- coding: utf-8 -*-
"""데이터랩 체류시간으로 앱의 일정 길이를 지역 단위로 검증한다.

    python -m pipeline.staytime

앱의 장소별 체류시간(`min`)은 근거가 없는 추정값이다. 고유값이 21개뿐이고
99.9%가 10분 배수라, 손으로 찍은 값이 분명하다. 그렇다고 데이터랩으로 장소별
값을 고칠 수는 없다 — 데이터랩 체류시간은 **지역 단위 1회 방문 총량**이고
앱의 min은 **장소당 관람시간**이라 단위가 다르다.

그래서 이 스크립트는 장소값을 고치지 않는다. 대신 두 가지를 본다.

  ① 지역 체류시간 지수 — 전국 평균 대비 몇 배 머무는 지역인가.
     추천 일정의 길이를 지역마다 다르게 잡는 근거가 된다.
  ② 앱의 장소별 시간이 지역 특성을 반영하는가 — 오래 머무는 지역일수록
     앱도 시간을 길게 잡았는지 순위상관으로 잰다.

산출: data/derived/staytime.json, reports/staytime.md
"""
import json
import os
import sys
from collections import defaultdict

from .common import DERIVED, NFC, RAW, REPORTS, read_csv, spearman

# 순위상관을 낼 최소 표본. verify.py 와 같은 기준을 쓴다.
MIN_PAIRS = 5

# 데이터랩은 광역지자체(시도)와 기초지자체(시군구)를 **다른 파일**로 준다.
# 전국 평균도 따로다 (2025년 광역 2,499분 / 기초 1,048분). 섞으면 서울(광역)이
# 경주(기초)보다 무조건 오래 머무는 것처럼 보인다. 지역코드 자릿수로 가른다.
#   11    = 서울특별시   (광역, 2자리)
#   47130 = 경주시       (기초, 5자리)
TIERS = {"광역": "전국 광역지자체별 평균", "기초": "전국 기초지자체별 평균"}


def tier_of(code):
    return "광역" if len(str(code).strip()) <= 2 else "기초"


def load_national_stay():
    """'전국' 다운로드의 방문자 체류특성 → 시군구 단위 전수, 연도별.

    전국 파일이 지역별 파일보다 낫다. 이유가 두 가지다.
      - 전국 229개 시군구를 한 번에 준다 (지역별 파일은 그 시도만)
      - `시도명` 컬럼이 있어 **동명이인을 가른다**. '고성군'이 강원과 경남에
        각각 있는데, 지역별 파일에는 시도명이 없어 구분할 수 없었다.

    폴더명에 기간이 박혀 있다: 20260926132215_전국_202501-202512_…
    """
    out = defaultdict(dict)          # {(시도, 시군구): {연도: (체류, 숙박일)}}
    if not os.path.isdir(RAW):
        return out
    for d in sorted(os.listdir(RAW)):
        p = os.path.join(RAW, d)
        parts = NFC(d).split("_")
        if not os.path.isdir(p) or len(parts) < 3 or parts[1] != "전국":
            continue
        year = parts[2][:4]
        for f in os.listdir(p):
            if not NFC(f).endswith("방문자 체류특성.csv"):
                continue
            for r in read_csv(os.path.join(p, f)):
                try:
                    key = (NFC(r["시도명"]).strip(), NFC(r["시군구명"]).strip())
                    out[key][year] = (float(r["평균 체류시간"]),
                                      float(r["평균 숙박일수"]))
                except (ValueError, KeyError):
                    continue
    return out


def load_stay_profile():
    """지역별 다운로드의 방문자 체류특성 → {지역명: (tier, 체류, 숙박일)}.

    전국 파일이 없을 때의 폴백이다. 시도명이 없어 동명이인을 가르지 못한다.
    """
    out = {}
    for root, _, files in os.walk(RAW):
        if "전국" in NFC(os.path.basename(root)).split("_")[1:2]:
            continue
        for f in files:
            if not NFC(f).endswith("방문자 체류특성.csv"):
                continue
            for r in read_csv(os.path.join(root, f)):
                if "지역명" not in r:
                    continue
                name = NFC(r["지역명"]).strip()
                try:
                    out[name] = (tier_of(r["지역코드"]),
                                 float(r["평균 체류시간"]),
                                 float(r["평균 숙박일수"]))
                except (ValueError, KeyError):
                    continue
    return out


def load_trend():
    """평균 체류시간 추이 → {tier: {연도: 전국평균}}, {지역명: {연도: 체류시간}}."""
    national, regional = defaultdict(dict), defaultdict(dict)
    for root, _, files in os.walk(RAW):
        for f in files:
            if not NFC(f).endswith("평균 체류시간 추이.csv"):
                continue
            for r in read_csv(os.path.join(root, f)):
                name, year = NFC(r["지역명"]).strip(), NFC(r["기준연월"]).strip()
                try:
                    v = float(r["체류시간(분)"])
                except (ValueError, KeyError):
                    continue
                hit = [t for t, label in TIERS.items() if name == label]
                if hit:
                    national[hit[0]][year] = v
                else:
                    regional[name][year] = v
    return national, regional


def load_lodging_ratio():
    """순 방문자 수 및 숙박 비율 → 폴더별 최신 연도의 숙박자 비율."""
    out = {}
    for root, _, files in os.walk(RAW):
        for f in files:
            if not NFC(f).endswith("순 방문자 수 및 숙박 비율.csv"):
                continue
            region = NFC(os.path.basename(root)).split("_")[1]
            rows = read_csv(os.path.join(root, f))
            latest = max(rows, key=lambda r: NFC(r["기준연월"]))
            try:
                out[region] = (NFC(latest["기준연월"]),
                               float(latest["숙박자 비율"]))
            except (ValueError, KeyError):
                continue
    return out


def simplify(name):
    """데이터랩 지역명 → 앱 locKo. '경주시'→'경주', '서울특별시'→'서울'.

    '창원시 마산합포구'처럼 구까지 쪼개져 오면 첫 어절(시)만 쓴다. 앱은 창원을
    한 덩어리로 다루기 때문이다.
    """
    import re
    n = NFC(name).strip().split()[0]
    return re.sub(r"(특별자치|특별|광역)?[시군구도]$", "", n) or n


# 앱이 광역 단위로 다루는 지역. 시군구가 아니라 시도명으로 묶는다.
WIDE = ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "제주")
# 같은 이름의 군이 두 시도에 있어 앱이 따로 표기하는 것.
DISAMBIG = {("강원특별자치도", "고성군"): "고성(강원)",
            ("강원도", "고성군"): "고성(강원)"}


def to_loc(sido, sigungu):
    """(시도명, 시군구명) → 앱 locKo. 동명이인은 시도명으로 가른다."""
    key = (NFC(sido).strip(), NFC(sigungu).strip())
    if key in DISAMBIG:
        return DISAMBIG[key]
    wide = simplify(sido)
    if wide in WIDE:                     # 서울 종로구 → '서울'
        return wide
    return simplify(sigungu)


def merge_subdistricts(profile):
    """구 단위로 쪼개진 지역을 시 단위로 합친다.

    데이터랩은 창원시를 5개 구, 포항시를 2개 구로 준다. 그대로 두면 앱 장소가
    구마다 중복 집계되고, 같은 도시가 표에 여러 번 나온다.

    방문자 수 가중치가 없어서 **단순 평균**으로 합친다. 구별 방문 규모가
    다르면 실제 시 평균과 어긋날 수 있으므로, 합친 구 수를 함께 남긴다.
    """
    groups = defaultdict(list)
    for name, (tier, stay, nights) in profile.items():
        groups[(simplify(name), tier)].append((name, stay, nights))
    out = {}
    for (loc, tier), members in groups.items():
        stay = sum(m[1] for m in members) / len(members)
        nights = sum(m[2] for m in members) / len(members)
        out[loc] = {
            "tier": tier, "stayMinutes": round(stay, 1),
            "lodgingDays": round(nights, 2),
            "subUnits": len(members),
            "subUnitNames": sorted(m[0] for m in members) if len(members) > 1 else [],
        }
    return out


def main():
    if not os.path.isdir(RAW):
        sys.exit(f"{RAW} 가 없습니다. 데이터랩 다운로드 폴더를 먼저 넣어 주세요.")
    places_path = os.path.join(DERIVED, "places.json")
    if not os.path.exists(places_path):
        sys.exit("data/derived/places.json 이 없습니다. "
                 "먼저 `python -m pipeline.places` 를 돌려 주세요.")
    places = json.load(open(places_path, encoding="utf-8"))["places"]

    profile = load_stay_profile()
    national, regional = load_trend()
    lodging = load_lodging_ratio()
    if not profile and not load_national_stay():
        sys.exit("체류시간 CSV가 없습니다. 데이터랩 '방문자 체류특성' 탭을 받아 주세요.")

    # 앱 장소를 지역별로 묶는다. 체류시간이 없는 장소는 평균에서 뺀다.
    by_region = defaultdict(list)
    for p in places:
        if p["region"] and p["stayMin"]:
            by_region[p["region"]].append(p)

    latest_year = max((y for d in national.values() for y in d), default=None)

    national_stay = load_national_stay()
    if national_stay:
        # 전국 파일이 있으면 그쪽을 쓴다. 시군구 전수 + 시도명으로 동명이인 해소.
        latest_year = max(y for v in national_stay.values() for y in v)
        agg = defaultdict(list)
        for (sido, sigungu), years in national_stay.items():
            if latest_year not in years:
                continue
            agg[to_loc(sido, sigungu)].append(years[latest_year])
        merged = {}
        for loc, vals in agg.items():
            merged[loc] = {
                "tier": "기초",
                # 서울·부산처럼 앱이 광역으로 묶는 곳은 자치구 평균이다.
                # 방문자 수 가중치가 없어 단순 평균을 쓴다.
                "stayMinutes": round(sum(v[0] for v in vals) / len(vals), 1),
                "lodgingDays": round(sum(v[1] for v in vals) / len(vals), 2),
                "subUnits": len(vals), "subUnitNames": [],
            }
        base_all = [m["stayMinutes"] for m in merged.values()]
        national.setdefault("기초", {})[latest_year] = round(
            sum(base_all) / len(base_all), 1)
        source = f"전국 다운로드 ({latest_year}년, 시군구 {len(national_stay)}개)"
    else:
        merged = merge_subdistricts(profile)
        source = "지역별 다운로드"

    rows = []
    for loc, m in sorted(merged.items()):
        tier, stay, nights = m["tier"], m["stayMinutes"], m["lodgingDays"]
        base = national.get(tier, {}).get(latest_year)
        app = by_region.get(loc, [])
        mins = [p["stayMin"] for p in app]
        rows.append({
            "region": loc,
            "tier": tier,
            "subUnits": m["subUnits"],
            "subUnitNames": m["subUnitNames"],
            "stayMinutes": stay,
            "lodgingDays": nights,
            # 전국 평균 대비 지수. 같은 tier 안에서만 의미가 있다.
            "index": round(stay / base, 3) if base else None,
            "appPlaces": len(app),
            "appStayMinSum": sum(mins) if mins else None,
            "appStayMinMean": round(sum(mins) / len(mins), 1) if mins else None,
            # 앱 장소를 다 보려면 몇 번 방문해야 하는가
            "visitsToSeeAll": round(sum(mins) / stay, 2) if mins and stay else None,
        })

    os.makedirs(DERIVED, exist_ok=True)
    dst = os.path.join(DERIVED, "staytime.json")
    json.dump({
        "latestYear": latest_year,
        "source": source,
        "nationalAverage": {t: national.get(t, {}) for t in TIERS},
        "lodgingRatio": lodging,
        "trend": {k: v for k, v in regional.items()},
        "regions": rows,
    }, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    report = write_report(rows, national, regional, lodging, latest_year)

    matched = [r for r in rows if r["appPlaces"]]
    print(f"출처: {source}")
    print(f"데이터랩 체류시간 지역 {len(rows)}곳 "
          f"(광역 {sum(1 for r in rows if r['tier']=='광역')} / "
          f"기초 {sum(1 for r in rows if r['tier']=='기초')})")
    print(f"그중 앱에 장소가 있는 지역 {len(matched)}곳")
    print(f"\n완료 → {dst}\n       {report}")


def write_report(rows, national, regional, lodging, year):
    L = ["# 체류시간 지역 검증\n"]
    L.append("데이터랩의 지역 체류시간으로 앱의 일정 길이가 현실적인지 확인한다.\n")

    L.append("## 먼저 — 두 숫자는 단위가 다르다\n")
    L.append("| | 무엇 | 값의 크기 |")
    L.append("|---|---|---|")
    L.append("| 데이터랩 `평균 체류시간` | 그 지역에 **1회 방문해 머문 총 시간** "
             "(이동·식사·숙박 포함) | 1,000~4,900분 |")
    L.append("| 앱 `stayMin` | **장소 한 곳의 관람 권장시간** | 40~90분 |")
    L.append("")
    L.append("직접 비교하거나, 데이터랩 값으로 앱의 장소별 값을 고칠 수 없다. "
             "지역 단위로만 맞대어 본다.\n")

    L.append("## 전국 평균\n")
    L.append("데이터랩은 광역지자체와 기초지자체를 다른 기준으로 준다. "
             "**섞으면 안 된다** — 서울(광역)이 경주(기초)보다 무조건 오래 "
             "머무는 것처럼 보인다.\n")
    L.append("| 구분 | " + " | ".join(sorted(national.get("기초", {}))) + " |")
    L.append("|---|" + "---|" * len(national.get("기초", {})))
    for t in ("광역", "기초"):
        d = national.get(t, {})
        if d:
            L.append(f"| 전국 {t} 평균 | "
                     + " | ".join(f"{d[y]:,.0f}분" for y in sorted(d)) + " |")
    L.append("")

    for tier in ("기초", "광역"):
        sel = [r for r in rows if r["tier"] == tier and r["appPlaces"]]
        if not sel:
            continue
        L.append(f"## {tier}지자체 — 체류시간 지수와 앱 장소\n")
        L.append("`지수`는 같은 tier 전국 평균 대비 배수다. "
                 "**추천 일정의 길이를 지역마다 다르게 잡는 근거**로 쓸 수 있다.\n")
        L.append("| 지역 | 체류시간 | 지수 | 숙박일 | 앱 장소 | 앱 시간합 | "
                 "장소평균 | 다 보려면 |")
        L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for r in sorted(sel, key=lambda x: -(x["index"] or 0)):
            mark = f" ˢ{r['subUnits']}" if r["subUnits"] > 1 else ""
            L.append(f"| {r['region']}{mark} | {r['stayMinutes']:,.0f}분 | "
                     f"{r['index'] if r['index'] else '—'} | {r['lodgingDays']} | "
                     f"{r['appPlaces']} | {r['appStayMinSum']:,}분 | "
                     f"{r['appStayMinMean']}분 | {r['visitsToSeeAll']}회 |")
        if any(r["subUnits"] > 1 for r in sel):
            merged_names = ", ".join(
                f"{r['region']}({r['subUnits']}개 구)"
                for r in sel if r["subUnits"] > 1)
            L.append(f"ˢ 표시는 데이터랩이 구 단위로 준 것을 시 단위로 합친 "
                     f"지역이다 — {merged_names}. 방문자 수 가중치가 없어 "
                     f"단순 평균을 썼다.\n")
        L.append("")

        xs = [r["stayMinutes"] for r in sel]
        ys = [r["appStayMinMean"] for r in sel]
        if len(sel) >= MIN_PAIRS:
            rho = spearman(xs, ys)
            L.append(f"**지역 체류시간 ↔ 앱 장소평균 시간 순위상관 "
                     f"{rho:+.2f}** (n={len(sel)})\n")
            if abs(rho) < 0.3:
                L.append("상관이 거의 없다. 앱의 장소별 체류시간이 지역 특성을 "
                         "반영하지 않는다는 뜻이다. 손으로 찍은 값이라는 진단과 "
                         "일치한다.\n")
            elif rho > 0:
                L.append("양의 상관이 있다. 오래 머무는 지역일수록 앱도 장소당 "
                         "시간을 길게 잡았다.\n")
            else:
                L.append("음의 상관이다. 오래 머무는 지역일수록 앱은 오히려 짧게 "
                         "잡았다는 뜻이라, 확인이 필요하다.\n")
        else:
            L.append(f"순위상관 측정 불가 — 앱 장소가 있는 지역이 {len(sel)}곳뿐이다 "
                     f"(최소 {MIN_PAIRS}곳 필요).\n")

    if lodging:
        L.append("## 숙박자 비율\n")
        L.append("당일치기와 숙박의 비중이다. 1박 이상 일정을 제안할지 "
                 "판단하는 근거가 된다.\n")
        L.append("| 지역 | 기준연도 | 숙박자 비율 |")
        L.append("|---|---|---:|")
        for reg, (y, v) in sorted(lodging.items()):
            L.append(f"| {reg} | {y} | {v}% |")
        L.append("")

    trend_sel = {k: v for k, v in regional.items() if v}
    if trend_sel:
        L.append("## 연도별 추이\n")
        years = sorted({y for v in trend_sel.values() for y in v})
        L.append("| 지역 | " + " | ".join(years) + " |")
        L.append("|---|" + "---:|" * len(years))
        for k, v in sorted(trend_sel.items()):
            L.append(f"| {k} | "
                     + " | ".join(f"{v[y]:,.0f}분" if y in v else "—"
                                  for y in years) + " |")
        L.append("")

    L.append("## 결론\n")
    L.append("- 앱의 `stayMin` 은 **고치지 않는다.** 데이터랩으로 장소별 값을 "
             "검증할 방법이 없다\n")
    L.append("- 대신 `index`(전국 평균 대비 배수)를 추천 일정 길이에 곱하면, "
             "지역 특성을 반영한 일정을 만들 수 있다\n")
    L.append("- `다 보려면` 이 1회를 크게 넘는 지역은 앱이 장소를 과하게 "
             "담고 있다는 뜻이다. 1회 방문 추천은 그보다 적게 골라야 한다\n")

    os.makedirs(REPORTS, exist_ok=True)
    dst = os.path.join(REPORTS, "staytime.md")
    open(dst, "w", encoding="utf-8").write("\n".join(L))
    return dst


if __name__ == "__main__":
    main()
