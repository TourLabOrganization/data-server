# -*- coding: utf-8 -*-
"""데이터랩 데이터가 앱과 실제로 맞물리는지 검증하고 지표 3개를 찍는다.

    python -m pipeline.verify

새 지역 CSV를 받을 때마다 돌리면 매칭률이 어떻게 변하는지 바로 보인다.
앱의 .dc.html 을 읽으므로, 앱 레포가 옆에 없으면 APP_REPO 환경변수로 경로를 준다.
"""
import os
import sys
from collections import defaultdict

from .common import (NFC, RAW, datalab_rows, find_match, load_region_map,
                     norm_name, norm_region, spearman)
from .places import extract

# 데이터랩 '인기관광지'는 통신·카드 기반 방문지라 관광지가 아닌 것이 섞여 있다.
# 모수를 3단으로 나눠서 매칭률을 정직하게 보고한다.
NOT_TOURISM = {"호텔", "콘도미니엄", "교통시설", "모텔", "펜션", "펜션/민박",
               "게스트하우스"}
# 앱에는 쇼핑 카테고리 자체가 없다(cat: heal·herit·activity·food·sea·stay).
# 백화점·아울렛은 앱이 다룰 수 없는 대상이므로 매칭률 분모에서 빼고 따로 센다.
# 전통시장은 앱이 food로 다루므로 여기 넣지 않는다.
OUT_OF_SCOPE = {"백화점", "쇼핑몰", "대형마트", "면세점"}

# 순위상관을 낼 최소 표본. 이보다 적으면 수치가 우연에 휘둘려 의미가 없다.
MIN_PAIRS = 5

def app_places_by_region():
    """앱 장소를 지역명으로 묶는다. {지역명: [장소, …]}.

    예전에는 verify 가 HTML을 따로 파싱하면서 **영문 블록키**로 찾았다. 그런데
    앱 장소의 72%(846곳·109개 지역)는 전용 블록 없이 `nation` 안에 있고 그
    지역명이 한글(`locKo`)이라, 영문 키로는 영원히 0곳이 나왔다. 전용 블록이
    있는 6곳 말고는 지역을 아무리 추가해도 조용히 "데이터 부족"으로 넘어갔다.

    이제 places.py 의 추출을 그대로 쓴다. 파싱이 한 곳으로 모이고, 전용 블록과
    nation 을 구분할 필요도 없어진다.
    """
    by = defaultdict(list)
    for p in extract():
        if p["region"]:
            by[p["region"]].append(p)
    return by


def datalab_regions():
    """받아둔 데이터랩 다운로드에서 검증 대상 지역을 뽑는다.

    목록을 코드에 박아두면 새 지역 CSV를 넣어도 검증에서 빠진다. 폴더명에서
    읽어 자동으로 늘어나게 한다.
    """
    if not os.path.isdir(RAW):
        return []
    table = load_region_map()
    out = {}
    for d in sorted(os.listdir(RAW)):
        if not os.path.isdir(os.path.join(RAW, d)):
            continue
        parts = NFC(d).split("_")
        if len(parts) < 2 or parts[1] == "전국":   # 전국은 지역이 아니라 기준값
            continue
        out[norm_region(parts[1], table)] = parts[1]
    return sorted(out.items())


def check(region_ko, region_raw, by_region):
    app = by_region.get(region_ko, [])
    pop = datalab_rows(region_raw, "인기관광지_전체.csv")
    if not app or not pop:
        print(f"  {region_ko}: 데이터 부족 "
              f"(앱 {len(app)}곳 / 데이터랩 {len(pop)}행) — 건너뜀")
        return None

    idx = {}
    for p in app:
        idx.setdefault(norm_name(p["nameKo"]), p)

    # 모수 3단. 데이터랩 TOP100에는 공항·호텔·백화점이 섞여 있어서, 전체를
    # 분모로 쓰면 앱이 애초에 다루지 않는 대상까지 '놓친 것'으로 잡힌다.
    lodging = [r for r in pop if NFC(r["분류"]) in NOT_TOURISM]
    shops = [r for r in pop if NFC(r["분류"]) in OUT_OF_SCOPE]
    scope = [r for r in pop if NFC(r["분류"]) not in NOT_TOURISM
             and NFC(r["분류"]) not in OUT_OF_SCOPE]

    exact = partial = 0
    matched = {}                             # 앱 장소 → 데이터랩 순위
    for r in scope:
        hit, how = find_match(r["관광지명"], idx)
        if not hit:
            continue
        exact += how == "exact"
        partial += how == "partial"
        matched.setdefault(norm_name(hit["nameKo"]), int(r["순위"]))
    n_hit = exact + partial

    # 앱이 영상(yt) 우선으로 정렬한 순서 ↔ 데이터랩 인기 순위.
    # 데이터랩에 없는 장소는 순위를 매길 근거가 없다. 예전처럼 더미 순위
    # (len(pop)+1)를 채워 넣으면 그 더미가 상관계수를 지배해 버리므로,
    # 양쪽에 다 있는 장소만 가지고 잰다.
    ordered = sorted(app, key=lambda p: (not p["youtubeId"], p["inactive"]))
    xs, ys = [], []
    for i, p in enumerate(ordered[:20], 1):
        r = matched.get(norm_name(p["nameKo"]))
        if r is not None:
            xs.append(i)
            ys.append(r)
    rho = spearman(xs, ys) if len(xs) >= MIN_PAIRS else None

    top5 = sum(1 for r in scope[:5]
               if find_match(r["관광지명"],
                             {norm_name(p["nameKo"]): p for p in ordered[:5]})[0])

    print(f"\n── {region_ko} ──")
    print(f"  앱 장소 {len(app)}곳 / 데이터랩 인기관광지 {len(pop)}곳")
    print(f"     └ 숙박·교통 {len(lodging)}곳, 쇼핑시설 {len(shops)}곳 제외"
          f" → 앱 대상 {len(scope)}곳")
    print(f"  ① 앱 대상 매칭률          {n_hit}곳 / {len(scope)}곳"
          f"  ({n_hit/len(scope)*100:.0f}%)   [정확 {exact} · 부분 {partial}]")
    if rho is None:
        print(f"  ② 앱 순서 ↔ 인기도 순위상관  측정 불가"
              f" (양쪽에 다 있는 장소 {len(xs)}곳, 최소 {MIN_PAIRS}곳 필요)")
    else:
        print(f"  ② 앱 순서 ↔ 인기도 순위상관  {rho:+.2f}  (n={len(xs)})"
              f"   {'(음수 = 인기 있는 곳일수록 뒤로 밀림)' if rho < -0.3 else ''}")
    print(f"  ③ 데이터랩 TOP5 중 앱 추천 TOP5 포함  {top5}곳")
    return dict(region=region_ko, match=n_hit, scope=len(scope),
                rho=rho, pairs=len(xs), top5=top5)


def main():
    if not os.path.isdir(RAW):
        sys.exit(f"{RAW} 가 없습니다. 데이터랩 다운로드 폴더를 먼저 넣어 주세요.")
    print("=" * 56)
    print("데이터랩 ↔ 앱 연결 검증")
    print("=" * 56)
    by_region = app_places_by_region()
    done = [r for loc, raw in datalab_regions()
            if (r := check(loc, raw, by_region))]
    if not done:
        print("\n검증할 지역이 없습니다.")
        return
    print("\n" + "=" * 56)
    tot_hit = sum(d["match"] for d in done)
    tot_scope = sum(d["scope"] for d in done)
    print(f"검증한 지역 {len(done)}곳 — 앱 대상 매칭률 "
          f"{tot_hit}/{tot_scope} ({tot_hit/tot_scope*100:.0f}%)")
    rated = [d for d in done if d["rho"] is not None]
    if rated:
        avg = sum(d["rho"] for d in rated) / len(rated)
        print(f"순위상관을 낼 수 있었던 지역 {len(rated)}곳 — 평균 {avg:+.2f}")
        for d in rated:
            print(f"   {d['region']:10} {d['rho']:+.2f}  (n={d['pairs']})")
    skipped = [d["region"] for d in done if d["rho"] is None]
    if skipped:
        print(f"표본 부족으로 순위상관 측정 불가: {', '.join(skipped)}")


if __name__ == "__main__":
    main()
