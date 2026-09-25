# -*- coding: utf-8 -*-
"""한국관광 데이터랩 다운로드(CSV) → 지역×테마 강도 지수(TFI) JSON.

    python -m pipeline.datalab

데이터랩은 무단 수집을 금지하므로 크롤링하지 않는다. 사람이 사이트에서 내려받은
CSV를 data/datalab_raw/<다운로드폴더>/ 에 그대로 두면 이 스크립트가 읽는다.

산출: data/derived/datalab.json
"""
import json
import math
import os
import sys
from collections import Counter, defaultdict

from .common import (DERIVED, NFC, RAW, load_region_map, norm_region, pick,
                     read_csv, scan_downloads)
from .taxonomy import (DATALAB_ALIAS, datalab_class_to_mid, is_golf,
                       to_app_cat)

# TFI 축은 **앱 카테고리**를 쓴다. 앱·TourAPI·데이터랩이 같은 분류체계 위에
# 놓이도록 재분류한 결과를 살리기 위해서다 (pipeline/taxonomy.py).
#
# sea 가 빠져 있는 이유: 데이터랩 인기관광지는 분류를 **중분류까지만** 준다.
# NA02(자연경관 하천‧해양)에 강·호수와 해변이 같이 들어 있어서 바다만 뗄 수 없다.
# 앱 쪽은 TourAPI 소분류를 받아오므로 sea 를 나눌 수 있지만, 지역 단위 TFI 는
# 데이터랩이 줄 수 있는 해상도까지만 만든다. 없는 정보를 지어내지 않는다.
THEMES = ["herit", "heal", "activity", "food"]
THEME_KO = {"herit": "역사·문화유산", "heal": "자연·힐링",
            "activity": "체험·활동", "food": "미식"}

# 관광소비 '업종대분류' → 소비 축. 장소 개수 축과 **단위가 다르다**(소비액 비중).
# 같은 표에 나란히 두면 오해하므로 산출물에서 키를 따로 둔다.
BIZ_THEME = {"식음료업": "food", "쇼핑업": "shopping"}


def consumption_shares(files):
    """관광소비 업종 비중 → 소비 축(%). 장소 개수 축과 단위가 다르다."""
    path = pick(files, "관광소비_내국인.csv")
    if not path:
        return {}
    seen, out = set(), {}
    for r in read_csv(path):
        big = NFC(r.get("업종대분류명"))
        if big in seen:                      # 대분류 비율은 중분류마다 반복돼 있다
            continue
        seen.add(big)
        theme = BIZ_THEME.get(big)
        if theme:
            out[theme] = float(r.get("업종대분류 비율(%)") or 0)
    return out


def spot_shares(files):
    """인기관광지 분류 구성 → 앱 카테고리별 장소 비중(%).

    예전 구현은 분류 29종 중 7종만 테마로 매핑하면서 **분모에는 전부** 넣었다.
    테마공원·랜드마크관광·자연공원 같은 것이 분자에서 통째로 빠져서 역사·자연
    비중이 실제보다 낮게 나왔다. 이제 taxonomy 의 매핑을 써서 전부 분류하고,
    모르는 값은 조용히 넘기지 않고 돌려준다.

    모수에서 빼는 것:
      - 숙박(stay)·교통 등 앱이 다루지 않는 대상
      - 별칭 표에서 의도적으로 제외한 것('데이트코스'·'기타관광')
    """
    path = pick(files, "인기관광지_전체.csv")
    if not path:
        return {}, [], 0, 0
    cnt, unknown, total, golf = defaultdict(int), [], 0, 0
    for r in read_csv(path):
        raw = NFC(r.get("분류"))
        if is_golf(r.get("관광지명")):
            golf += 1                        # 앱이 다루지 않는 대상. 모수에서 뺀다
            continue
        mid = datalab_class_to_mid(raw)
        if mid is None:
            if raw not in DATALAB_ALIAS:
                unknown.append(raw)          # 모르는 값. 호출한 쪽이 보고한다
            continue                         # 별칭 표의 None 은 의도적 제외
        cat = to_app_cat(mid)
        if cat not in THEMES:                # stay·쇼핑시설·교통시설
            continue
        cnt[cat] += 1
        total += 1
    if not total:
        return {}, unknown, 0, golf
    return ({t: cnt[t] / total * 100 for t in THEMES}, unknown, total, golf)


def age_profile(files):
    """성·연령별 관광소비 분포. 카드 결제자 기준이라 '여행자'와 다를 수 있다."""
    path = pick(files, "성연령별 내국인 관광소비 분포.csv")
    if not path:
        return {}
    out = {}
    for r in read_csv(path):
        age = NFC(r.get("소비자 연령"))
        out[age] = {"남": float(r.get("비율(남성)") or 0),
                    "여": float(r.get("비율(여성)") or 0)}
    return out


def flows(files, table):
    """유입·유출 지역 비율 → 동선 그래프의 간선 후보."""
    path = pick(files, "연관지역.csv")
    if not path:
        return {"in": [], "out": []}
    # 데이터랩은 자치구 단위로 주는데 앱은 시 단위라, 같은 시가 여러 줄로 나뉜다
    # (울산 북구·남구·중구·울주군 → 모두 '울산'). 합산해야 실제 왕래 강도가 된다.
    agg = {"in": defaultdict(float), "out": defaultdict(float)}
    for r in read_csv(path):
        code = (r.get("유입/유출 구분 코드 (1:유입 / 2:유출)") or "").strip()
        side = "in" if code == "1" else "out"
        peer = r.get("유입지역명") if side == "in" else r.get("유출지역명")
        agg[side][norm_region(peer, table)] += float(r.get("유입유출 비율") or 0)
    return {s: [{"region": k, "ratio": round(v, 1)}
                for k, v in sorted(agg[s].items(), key=lambda x: -x[1])]
            for s in ("in", "out")}


def to_tfi(shares_by_region):
    """지역별 비중 → TFI(0~1).

    PDF의 log 입지계수(LQ)는 전국 기준값이 있어야 한다. 지역이 2곳 이상이면
    받은 지역들의 평균을 기준으로 상대 LQ를 내고, 1곳뿐이면 기준이 없으므로
    비중을 그대로 두고 tfi=null 로 남긴다(거짓 숫자를 만들지 않는다).
    """
    regions = list(shares_by_region)
    tfi = {r: {} for r in regions}
    for t in THEMES:
        vals = {r: shares_by_region[r].get(t) for r in regions
                if shares_by_region[r].get(t) is not None}
        if len(vals) < 2:
            for r in regions:
                tfi[r][t] = None
            continue
        base = sum(vals.values()) / len(vals)
        lq = {r: math.log((v or 1e-9) / base) if base else 0 for r, v in vals.items()}
        lo, hi = min(lq.values()), max(lq.values())
        for r in regions:
            tfi[r][t] = None if r not in lq else (
                0.5 if hi == lo else round((lq[r] - lo) / (hi - lo), 4))
    return tfi


def app_category_share(region):
    """앱 장소의 카테고리 분포(%). 재분류 결과(catOfficial)를 우선 쓴다.

    데이터랩과 달리 여기에는 sea 가 있다. TourAPI 소분류를 받아왔기 때문이다.
    categories.json 이 없으면 빈 값을 돌려준다(재분류 전에도 돌아가야 한다).
    """
    path = os.path.join(DERIVED, "categories.json")
    if not os.path.exists(path):
        return {}
    rows = json.load(open(path, encoding="utf-8"))["places"]
    cnt, total = defaultdict(int), 0
    for r in rows:
        if r.get("region") != region:
            continue
        cat = r.get("catOfficial") or r.get("catApp")
        if not cat or cat == "stay":
            continue
        cnt[cat] += 1
        total += 1
    return {k: round(v / total * 100, 1) for k, v in cnt.items()} if total else {}


def main():
    table = load_region_map()
    found = scan_downloads()
    if not found:
        sys.exit(f"{RAW} 에 데이터랩 다운로드 폴더가 없습니다.")

    shares, detail, unknown_all = {}, {}, defaultdict(list)
    for region_raw, files in found.items():
        loc = norm_region(region_raw, table)
        spot, unknown, n_spot, n_golf = spot_shares(files)
        consumption = consumption_shares(files)
        if unknown:
            unknown_all[loc].extend(unknown)

        # 장소 개수 축만 TFI 로 간다. 소비 축은 단위가 달라 섞지 않는다.
        merged = dict(spot)
        if "food" in consumption and "food" not in merged:
            merged["food"] = consumption["food"]
        shares[loc] = merged

        detail[loc] = {
            # 장소 개수 기준(%) — 인기관광지 분류 구성
            "spotShare": {k: round(v, 2) for k, v in spot.items()},
            "spotCount": n_spot,
            "golfExcluded": n_golf,
            # 소비액 기준(%) — 관광소비 업종 비중. 위와 단위가 다르다
            "consumptionShare": {k: round(v, 2) for k, v in consumption.items()},
            # 앱 장소의 분포. 재분류 결과라 sea 가 따로 있다
            "appCategoryShare": app_category_share(loc),
            "age_consumption": age_profile(files),
            "flows": flows(files, table),
            "source_files": sorted(files),
        }
        got = [t for t in THEMES if t in spot]
        print(f"  {loc}: 관광지 {n_spot}곳 분류 → 테마 {len(got)}/{len(THEMES)}개"
              + (f"  (골프장 {n_golf}곳 제외)" if n_golf else ""))

    tfi = to_tfi(shares)
    os.makedirs(DERIVED, exist_ok=True)
    out = {"themes": THEMES, "themeLabels": THEME_KO,
           "regions": sorted(shares), "tfi": tfi, "detail": detail}
    dst = os.path.join(DERIVED, "datalab.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if unknown_all:
        print("\n  ⚠️ 매핑하지 못한 데이터랩 분류값이 있습니다:")
        for loc, vals in unknown_all.items():
            for v, c in sorted(Counter(vals).items()):
                print(f"     {loc}: '{v}' {c}건")
        print("     pipeline/taxonomy.py 의 DATALAB_ALIAS 에 추가해 주세요.")
    if len(shares) < 2:
        print("\n  ⚠️ 지역이 1곳뿐이라 TFI(상대 비교)는 계산하지 못했습니다.")
        print("     비교 기준이 생기려면 지역이 2곳 이상 필요합니다.")
    print(f"\n완료 → {dst}")


if __name__ == "__main__":
    main()
