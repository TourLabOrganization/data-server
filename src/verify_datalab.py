# -*- coding: utf-8 -*-
"""데이터랩 데이터가 앱과 실제로 맞물리는지 검증하고 지표 3개를 찍는다.

    python src/verify_datalab.py

새 지역 CSV를 받을 때마다 돌리면 매칭률이 어떻게 변하는지 바로 보인다.
"""
import csv, os, re, sys, unicodedata
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "datalab_raw")
APP = os.environ.get("APP_REPO") or os.path.dirname(ROOT)

NFC = lambda s: unicodedata.normalize("NFC", s or "")
NOT_TOURISM = {"호텔", "콘도미니엄", "교통시설", "모텔", "펜션", "게스트하우스"}


def norm_name(s):
    """장소명 비교용. 괄호·공백·기호를 지우고 접두 '경주'를 뗀다."""
    s = re.sub(r"\(.*?\)|\[.*?\]", "", NFC(s))
    s = re.sub(r"[^가-힣A-Za-z0-9]", "", s)
    return s.lower()


def app_places(region_key):
    """앱의 .dc.html에서 해당 지역 장소를 뽑는다. 줄번호에 의존하지 않는다."""
    path = os.path.join(APP, "Tour Planner.dc.html")
    if not os.path.exists(path):
        sys.exit(f"앱 파일을 찾을 수 없습니다: {path}\nAPP_REPO 환경변수로 경로를 주세요.")
    src = open(path, encoding="utf-8").read()

    def block(key):
        m = re.search(rf"\b{key}\s*:\s*\{{", src)
        if not m:
            return []
        s = src.index("places:[", m.end()) + len("places:[")
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


def datalab_rows(region_raw, suffix):
    for d in sorted(os.listdir(RAW)):
        p = os.path.join(RAW, d)
        if not os.path.isdir(p) or region_raw not in NFC(d):
            continue
        for f in os.listdir(p):
            if NFC(f).endswith(suffix):
                return list(csv.DictReader(open(os.path.join(p, f), encoding="utf-8-sig")))
    return []


def spearman(a, b):
    n = len(a)
    if n < 3:
        return 0.0
    rank = lambda xs: {v: i + 1 for i, v in enumerate(sorted(xs))}
    ra, rb = rank(a), rank(b)
    A, B = [ra[x] for x in a], [rb[x] for x in b]
    ma, mb = sum(A) / n, sum(B) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(A, B))
    den = (sum((x - ma) ** 2 for x in A) * sum((y - mb) ** 2 for y in B)) ** .5
    return num / den if den else 0.0


def check(region_raw, block_key):
    app = app_places(block_key)
    pop = datalab_rows(region_raw, "인기관광지_전체.csv")
    if not app or not pop:
        print(f"  {block_key}: 데이터 부족 (앱 {len(app)}곳 / 데이터랩 {len(pop)}행) — 건너뜀")
        return None

    idx = {}
    for p in app:
        idx.setdefault(norm_name(p["ko"]), p)
    hit = [r for r in pop if norm_name(r["관광지명"]) in idx]
    clean = [r for r in pop if NFC(r["분류"]) not in NOT_TOURISM]

    # 앱이 영상(yt) 우선으로 정렬한 순서 ↔ 데이터랩 인기 순위
    rank = {norm_name(r["관광지명"]): int(r["순위"]) for r in pop}
    ordered = sorted(app, key=lambda p: (not p["yt"], p["off"]))
    xs, ys = [], []
    for i, p in enumerate(ordered[:10], 1):
        xs.append(i)
        ys.append(rank.get(norm_name(p["ko"]), len(pop) + 1))
    rho = spearman(xs, ys)
    top5 = sum(1 for r in clean[:5] if norm_name(r["관광지명"]) in
               {norm_name(p["ko"]) for p in ordered[:5]})

    print(f"\n── {block_key} ──")
    print(f"  앱 장소 {len(app)}곳 / 데이터랩 인기관광지 {len(pop)}곳")
    print(f"  ① 인기 TOP100 매칭률      {len(hit)}곳  ({len(hit)/len(pop)*100:.0f}%)")
    print(f"  ② 앱 순서 ↔ 인기도 순위상관  {rho:+.2f}"
          f"   {'(음수 = 인기 있는 곳일수록 뒤로 밀림)' if rho < 0 else ''}")
    print(f"  ③ 데이터랩 TOP5 중 앱 추천 TOP5 포함  {top5}곳")
    return dict(region=block_key, match=len(hit), rho=round(rho, 3), top5=top5)


def main():
    if not os.path.isdir(RAW):
        sys.exit(f"{RAW} 가 없습니다. 데이터랩 다운로드 폴더를 먼저 넣어 주세요.")
    # (다운로드 폴더명에 쓰이는 표기, 앱 DATA의 블록 키)
    targets = [("경주", "gyeongju"), ("거제", "geoje"), ("서울", "seoul"),
               ("부산", "busan"), ("제주", "jeju"), ("영월", "yeongwol")]
    print("=" * 56)
    print("데이터랩 ↔ 앱 연결 검증")
    print("=" * 56)
    done = [r for t, k in targets if (r := check(t, k))]
    if not done:
        print("\n검증할 지역이 없습니다.")
        return
    print("\n" + "=" * 56)
    print(f"검증한 지역 {len(done)}곳 — 평균 순위상관 "
          f"{sum(d['rho'] for d in done)/len(done):+.2f}")


if __name__ == "__main__":
    main()
