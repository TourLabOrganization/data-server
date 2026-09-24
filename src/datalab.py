# -*- coding: utf-8 -*-
"""한국관광 데이터랩 다운로드(CSV) → 지역×테마 강도 지수(TFI) JSON.

데이터랩은 무단 수집을 금지하므로 크롤링하지 않는다. 사람이 사이트에서 내려받은
CSV를 data/datalab_raw/<다운로드폴더>/ 에 그대로 두면 이 스크립트가 읽는다.

산출: data/derived/datalab.json
"""
import csv, json, os, re, sys, unicodedata
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "datalab_raw")
OUT = os.path.join(ROOT, "data", "derived")
MAP = os.path.join(ROOT, "data", "mapping", "regions.csv")

# macOS는 한글 파일명을 자모 분리(NFD)로 저장한다. 비교 전에 반드시 합쳐야 한다.
NFC = lambda s: unicodedata.normalize("NFC", s or "")

# 데이터랩 '인기관광지'는 통신·내비 기반 방문지라 숙박·교통·골프장이 섞여 있다.
# 관광 테마 비중을 계산할 때는 빼야 한다.
NOT_TOURISM = {"호텔", "콘도미니엄", "교통시설", "모텔", "펜션", "게스트하우스"}

# 인기관광지 '분류' → 표준 테마
SPOT_THEME = {
    "역사유적지": "역사·문화유산", "종교성지": "역사·문화유산",
    "전시시설": "역사·문화유산", "역사유물": "역사·문화유산",
    "자연경관(하천/해양)": "자연·힐링", "자연생태": "자연·힐링", "도시공원": "자연·힐링",
}
# 관광소비 '업종대분류' → 표준 테마
BIZ_THEME = {"식음료업": "미식", "쇼핑업": "쇼핑"}

THEMES = ["미식", "쇼핑", "역사·문화유산", "자연·힐링"]


def load_region_map():
    """'경상북도 경주시' 같은 데이터랩 표기를 앱의 locKo('경주')로 바꾸는 표.

    match=prefix 는 첫 어절만 맞아도 적용한다(광역시는 자치구를 무시해야 하므로).
    match=exact 는 전체가 정확히 같을 때만. '경상북도'를 prefix로 두면
    '경상북도 경주시'가 '경북'이 되어버리기 때문에 구분이 필요하다.
    """
    prefix, exact = {}, {}
    if not os.path.exists(MAP):
        return prefix, exact
    for r in csv.DictReader(open(MAP, encoding="utf-8-sig")):
        key, val = NFC(r["datalab"]).strip(), NFC(r["locKo"]).strip()
        (prefix if NFC(r.get("match", "")).strip() == "prefix" else exact)[key] = val
    return prefix, exact


def norm_region(name, table):
    """데이터랩 지역 표기 → 앱 locKo.

    데이터랩은 광역시를 자치구까지 쪼개 주지만('부산광역시 해운대구') 앱은 광역시를
    한 덩어리로 쓴다('부산'). 그래서 마지막 어절만 떼면 '해운대'가 되어 틀린다.
    첫 어절이 광역시·특별시·특별자치도면 그쪽을 우선한다.
    """
    prefix, exact = table
    n = re.sub(r"\s+", " ", NFC(name).strip())
    if n in exact:
        return exact[n]
    tok = n.split() or [n]
    if tok[0] in prefix:                    # 광역시·특별시·제주 → 자치구 무시
        return prefix[tok[0]]
    # '경상북도 포항시 남구'처럼 3단이면 가운데(시) 가 앱의 단위다. 마지막을
    # 쓰면 '남'이 되어 깨진다.
    core = tok[1] if len(tok) >= 3 else tok[-1]
    return re.sub(r"(특별자치)?[시군구도]$", "", core) or core


def scan_downloads():
    """다운로드 폴더들을 훑어 {지역: {파일종류: 경로}} 로 정리."""
    found = defaultdict(dict)
    if not os.path.isdir(RAW):
        return found
    for d in sorted(os.listdir(RAW)):
        p = os.path.join(RAW, d)
        if not os.path.isdir(p):
            continue
        # 폴더명 예: 20260924212535_경주시_2023-2025_데이터랩_다운로드
        parts = NFC(d).split("_")
        region = parts[1] if len(parts) > 1 else d
        for f in os.listdir(p):
            if f.lower().endswith(".csv"):
                # 앞의 타임스탬프만 떼고 나머지는 그대로 둔다. 탭에 따라
                # 'AI 관광 분석_연관지역.csv'처럼 중간 접두사가 더 붙기도 한다.
                found[region][NFC(f).split("_", 1)[-1]] = os.path.join(p, f)
    return found


def pick(files, suffix):
    """파일명이 suffix로 끝나는 첫 파일. 중간 접두사가 달라도 찾아낸다."""
    for k, v in files.items():
        if k.endswith(suffix):
            return v
    return None


def read(path):
    return list(csv.DictReader(open(path, encoding="utf-8-sig")))


def consumption_shares(files):
    """관광소비 업종 비중 → 미식·쇼핑 원시 비중(%)."""
    path = pick(files, "관광소비_내국인.csv")
    if not path:
        return {}
    seen, out = set(), {}
    for r in read(path):
        big = NFC(r.get("업종대분류명"))
        if big in seen:                      # 대분류 비율은 중분류마다 반복돼 있다
            continue
        seen.add(big)
        theme = BIZ_THEME.get(big)
        if theme:
            out[theme] = float(r.get("업종대분류 비율(%)") or 0)
    return out


def spot_shares(files):
    """인기관광지 분류 구성 → 역사·자연 테마 비중(%). 숙박·교통은 모수에서 제외."""
    path = pick(files, "인기관광지_전체.csv")
    if not path:
        return {}
    rows = [r for r in read(path) if NFC(r.get("분류")) not in NOT_TOURISM]
    if not rows:
        return {}
    cnt = defaultdict(int)
    for r in rows:
        t = SPOT_THEME.get(NFC(r.get("분류")))
        if t:
            cnt[t] += 1
    return {t: cnt[t] / len(rows) * 100 for t in ("역사·문화유산", "자연·힐링")}


def age_profile(files):
    """성·연령별 관광소비 분포. 카드 결제자 기준이라 '여행자'와 다를 수 있다."""
    path = pick(files, "성연령별 내국인 관광소비 분포.csv")
    if not path:
        return {}
    out = {}
    for r in read(path):
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
    for r in read(path):
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
    import math
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


def main():
    table = load_region_map()
    found = scan_downloads()
    if not found:
        sys.exit(f"{RAW} 에 데이터랩 다운로드 폴더가 없습니다.")

    shares, detail = {}, {}
    for region_raw, files in found.items():
        loc = norm_region(region_raw, table)
        s = {}
        s.update(consumption_shares(files))
        s.update(spot_shares(files))
        shares[loc] = s
        detail[loc] = {"share_pct": s,
                       "age_consumption": age_profile(files),
                       "flows": flows(files, table),
                       "source_files": sorted(files)}
        got = [t for t in THEMES if t in s]
        print(f"  {loc}: 테마 {len(got)}/{len(THEMES)}개 계산 {got}")

    tfi = to_tfi(shares)
    os.makedirs(OUT, exist_ok=True)
    out = {"themes": THEMES, "regions": sorted(shares), "tfi": tfi, "detail": detail}
    dst = os.path.join(OUT, "datalab.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if len(shares) < 2:
        print("\n  ⚠️ 지역이 1곳뿐이라 TFI(상대 비교)는 계산하지 못했습니다.")
        print("     비교 기준이 생기려면 지역이 2곳 이상 필요합니다.")
    print(f"\n완료 → {dst}")


if __name__ == "__main__":
    main()
