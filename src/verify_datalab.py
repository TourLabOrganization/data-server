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

# 데이터랩은 지역명을 앞에 붙여 표기한다('경주불국사경내'). 앱은 안 붙인다.
REGION_PREFIX = ("경주", "거제", "서울", "제주", "부산", "영월", "서귀포")
# 데이터랩 쪽에만 붙는 꼬리표. 같은 장소를 다른 이름으로 만든다.
NAME_TAIL = ("경내", "관광지", "유원지", "일원", "지구")


def norm_name(s):
    """장소명 비교용. 괄호·공백·기호와 지역 접두사·꼬리표를 떼어 맞춘다.

    '경주불국사경내'(데이터랩)와 '불국사'(앱)가 같은 곳으로 잡혀야 한다.
    """
    s = re.sub(r"\(.*?\)|\[.*?\]", "", NFC(s))
    s = re.sub(r"[^가-힣A-Za-z0-9]", "", s).lower()
    for p in REGION_PREFIX:                 # 접두 지역명은 한 번만 뗀다
        if s.startswith(p) and len(s) > len(p) + 1:
            s = s[len(p):]
            break
    for t in NAME_TAIL:
        if s.endswith(t) and len(s) > len(t) + 1:
            s = s[: -len(t)]
            break
    return s


# 포함관계여도 다른 장소인 경우. '산방산'과 '산방산탄산온천'은 별개다.
# 이름이 짧은 쪽에 이 단어들이 덧붙어 길어졌다면 시설이 바뀐 것으로 본다.
DIFFERENT_PLACE = ("온천", "호텔", "리조트", "컨벤션", "터미널", "골프",
                   "cc", "아울렛", "백화점", "휴게소")


def find_match(dl_name, idx):
    """데이터랩 장소명 → 앱 장소. 정확 매칭 후 포함관계까지 본다.

    '신선대전망대'(데이터랩) ↔ '신선대'(앱) 같은 쌍을 잡기 위한 것이다.
    2글자 이하로는 포함 매칭을 하지 않는다('산'이 아무 데나 붙는다).
    """
    n = norm_name(dl_name)
    if n in idx:
        return idx[n], "exact"
    for an, p in idx.items():
        if len(an) < 3 or not (an in n or n in an):
            continue
        # 긴 쪽에서 짧은 쪽을 뺀 나머지가 '다른 시설'을 가리키면 버린다
        rest = (n if len(n) > len(an) else an).replace(
            an if len(n) > len(an) else n, "")
        if any(w in rest for w in DIFFERENT_PLACE):
            continue
        return p, "partial"
    return None, None


def app_places(region_key):
    """앱의 .dc.html에서 해당 지역 장소를 뽑는다. 줄번호에 의존하지 않는다."""
    path = os.path.join(APP, "Tour Planner.dc.html")
    if not os.path.exists(path):
        sys.exit(f"앱 파일을 찾을 수 없습니다: {path}\nAPP_REPO 환경변수로 경로를 주세요.")
    src = open(path, encoding="utf-8").read()
    # 'seoul:' 'geoje:' 같은 키는 ORIGINS·REGION_HUB에도 있어서, DATA 밖에서 먼저
    # 걸리면 엉뚱한 블록을 읽는다. 반드시 DATA 시작점 뒤에서만 찾는다.
    data_at = src.find("const DATA")
    if data_at < 0:
        data_at = 0

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
    """순위상관. 동점은 평균순위로 처리한다.

    예전 구현은 순위표를 {값: 위치} dict로 만들어서 같은 값이 여러 개면
    마지막 하나만 남고 나머지가 사라졌다. 미매칭 장소에 전부 같은 더미 순위를
    주는 구조라 동점이 대량으로 생기는데, 그게 상관계수를 실제보다 크게
    보이게 만들었다(서울 -0.52는 더미값 9개가 만든 숫자였다).
    """
    n = len(a)
    if n < 3:
        return 0.0

    def rank(xs):
        order = sorted(range(n), key=lambda i: xs[i])
        r, i = [0.0] * n, 0
        while i < n:
            j = i
            while j + 1 < n and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1            # 동점 구간은 평균순위를 나눠 갖는다
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    A, B = rank(a), rank(b)
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

    # 모수 3단. 데이터랩 TOP100에는 공항·호텔·백화점이 섞여 있어서, 전체를
    # 분모로 쓰면 앱이 애초에 다루지 않는 대상까지 '놓친 것'으로 잡힌다.
    lodging = [r for r in pop if NFC(r["분류"]) in NOT_TOURISM]
    shops = [r for r in pop if NFC(r["분류"]) in OUT_OF_SCOPE]
    scope = [r for r in pop if NFC(r["분류"]) not in NOT_TOURISM
             and NFC(r["분류"]) not in OUT_OF_SCOPE]

    exact = partial = 0
    matched = {}                             # 데이터랩 순위 → 앱 장소
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
               if find_match(r["관광지명"], {norm_name(p["ko"]): p
                                          for p in ordered[:5]})[0])

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
