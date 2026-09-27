# -*- coding: utf-8 -*-
"""데이터랩 '인기관광지' 순위를 앱 장소에 붙인다.

    python -m pipeline.popularity

산출: data/derived/popularity.json  — {장소id: 순위}

**이건 정렬 키가 아니라 배지용이다.** 데이터랩을 받아 둔 지역만 순위가 있어서
앱 장소 3,118곳 중 200여 곳에만 값이 붙는다. 이걸로 목록을 정렬하면 나머지
93%가 "순위 없음" 하나로 뭉뚱그려져 뒤로 밀린다. 화면에 "데이터랩 인기 3위"
같은 배지를 다는 데만 쓴다.

지역 CSV를 더 받을수록 커버리지가 는다(한 지역당 20~56곳). 받은 만큼만
늘어나고, 없는 지역은 조용히 비어 있는다.

산출물은 커밋한다 — 원본 CSV 는 재배포할 수 없어서(CLAUDE.md 1번) 이 결과가
없으면 다른 사람이 받은 데이터랩 없이는 다시 만들 수 없다.
"""
import json
import os
import sys

from .common import DERIVED, datalab_rows, find_match, norm_name
from .places import extract
from .verify import NOT_TOURISM, OUT_OF_SCOPE, app_places_by_region, datalab_regions

# 데이터랩 인기관광지 CSV. '_전체' 는 현지인·외지인을 합친 것이다.
SRC = "인기관광지_전체.csv"


def ranks():
    """{장소id: 순위}. 같은 장소가 여러 번 걸리면 더 높은 순위를 남긴다."""
    by = app_places_by_region()
    out, per_region = {}, {}
    for region, region_raw in datalab_regions():
        rows = datalab_rows(region_raw, SRC)
        places = by.get(region, [])
        if not rows or not places:
            continue
        idx = {norm_name(p["nameKo"]): p for p in places}
        hit = 0
        for r in rows:
            # 호텔·교통시설·백화점은 앱이 다루는 대상이 아니다. 순위에서도 뺀다.
            if r.get("분류") in NOT_TOURISM or r.get("분류") in OUT_OF_SCOPE:
                continue
            p, _ = find_match(r["관광지명"], idx)
            if not p:
                continue
            rank = int(r["순위"])
            if p["id"] not in out or rank < out[p["id"]]:
                if p["id"] not in out:
                    hit += 1
                out[p["id"]] = rank
        per_region[region] = hit
    return out, per_region


def main():
    total = len(extract())
    out, per_region = ranks()
    os.makedirs(DERIVED, exist_ok=True)
    dst = os.path.join(DERIVED, "popularity.json")
    json.dump({"source": f"한국관광 데이터랩 {SRC}", "count": len(out),
               "ranks": dict(sorted(out.items(), key=lambda kv: kv[1]))},
              open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    for region, n in sorted(per_region.items()):
        print(f"  {region:<6} 순위 붙은 장소 {n:>3}곳")
    print(f"\n장소 {total}곳 중 {len(out)}곳에 순위 ({len(out) / total * 100:.1f}%)")
    if not out:
        print("  ⚠️ 데이터랩 다운로드가 없습니다. data/datalab_raw/README.md 참고.\n"
              "     popularity.json 을 비운 채 커밋하지 마세요 — 배지가 전부 사라집니다.")
    print(f"완료 → {dst}")


if __name__ == "__main__":
    main()
