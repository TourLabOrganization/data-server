# -*- coding: utf-8 -*-
"""데이터랩 데이터가 앱과 실제로 맞물리는지 검증하고 지표 3개를 찍는다.

    python -m pipeline.verify

새 지역 CSV를 받을 때마다 돌리면 매칭률이 어떻게 변하는지 바로 보인다.
앱의 .dc.html 을 읽으므로, 앱 레포가 옆에 없으면 APP_REPO 환경변수로 경로를 준다.
"""
import os
import re
import sys

from .common import (APP_HTML, NFC, RAW, datalab_rows, find_match,
                     norm_name, spearman)

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

# (다운로드 폴더명에 쓰이는 표기, 앱 DATA의 블록 키)
TARGETS = [("경주", "gyeongju"), ("거제", "geoje"), ("서울", "seoul"),
           ("부산", "busan"), ("제주", "jeju"), ("영월", "yeongwol")]


def app_places(region_key):
    """앱의 .dc.html에서 해당 지역 장소를 뽑는다. 줄번호에 의존하지 않는다."""
    if not os.path.exists(APP_HTML):
        sys.exit(f"앱 파일을 찾을 수 없습니다: {APP_HTML}\n"
                 f"APP_REPO 환경변수로 앱 레포 경로를 주세요.")
    src = open(APP_HTML, encoding="utf-8").read()
    # 'seoul:' 'geoje:' 같은 키는 ORIGINS·REGION_HUB에도 있어서, DATA 밖에서 먼저
    # 걸리면 엉뚱한 블록을 읽는다. 반드시 DATA 시작점 뒤에서만 찾는다.
    data_at = max(src.find("const DATA"), 0)

    def block(key):
        m = re.search(rf"\b{key}\s*:\s*\{{", src[data_at:])
        if not m:
            return []
        s = src.index("places:[", data_at + m.end()) + len("places:[")
        depth, i = 1, s
        while depth and i < len(src):
            if src[i] == "[":
                depth += 1
            elif src[i] == "]":
                depth -= 1
            i += 1
        out = []
        for rec in re.findall(r"\{[^{}]*\}", src[s:i - 1]):
            g = lambda k: (re.search(rf"\b{k}:'([^']*)'", rec) or [None, None])[1]
            if g("id") and g("ko"):
                out.append(dict(id=g("id"), ko=g("ko"), yt=bool(g("yt")),
                                off="off:true" in rec, locKo=g("locKo")))
        return out

    named = block(region_key)
    nation = [p for p in block("nation") if p.get("locKo") == NFC(region_key)]
    return named + nation


def check(region_raw, block_key):
    app = app_places(block_key)
    pop = datalab_rows(region_raw, "인기관광지_전체.csv")
    if not app or not pop:
        print(f"  {block_key}: 데이터 부족 (앱 {len(app)}곳 / 데이터랩 {len(pop)}행) — 건너뜀")
        return None

    idx = {}
    for p in app:
        idx.setdefault(norm_name(p["ko"]), p)

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
        matched.setdefault(norm_name(hit["ko"]), int(r["순위"]))
    n_hit = exact + partial

    # 앱이 영상(yt) 우선으로 정렬한 순서 ↔ 데이터랩 인기 순위.
    # 데이터랩에 없는 장소는 순위를 매길 근거가 없다. 예전처럼 더미 순위
    # (len(pop)+1)를 채워 넣으면 그 더미가 상관계수를 지배해 버리므로,
    # 양쪽에 다 있는 장소만 가지고 잰다.
    ordered = sorted(app, key=lambda p: (not p["yt"], p["off"]))
    xs, ys = [], []
    for i, p in enumerate(ordered[:20], 1):
        r = matched.get(norm_name(p["ko"]))
        if r is not None:
            xs.append(i)
            ys.append(r)
    rho = spearman(xs, ys) if len(xs) >= MIN_PAIRS else None

    top5 = sum(1 for r in scope[:5]
               if find_match(r["관광지명"],
                             {norm_name(p["ko"]): p for p in ordered[:5]})[0])

    print(f"\n── {block_key} ──")
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
    return dict(region=block_key, match=n_hit, scope=len(scope),
                rho=rho, pairs=len(xs), top5=top5)


def main():
    if not os.path.isdir(RAW):
        sys.exit(f"{RAW} 가 없습니다. 데이터랩 다운로드 폴더를 먼저 넣어 주세요.")
    print("=" * 56)
    print("데이터랩 ↔ 앱 연결 검증")
    print("=" * 56)
    done = [r for t, k in TARGETS if (r := check(t, k))]
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
