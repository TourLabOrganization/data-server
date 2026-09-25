# -*- coding: utf-8 -*-
"""파이프라인 공용 유틸. 경로·한글 정규화·지역명 변환을 한 곳에서 관리한다.

datalab.py 와 verify.py 가 같은 로직을 각자 들고 있어서 한쪽만 고치면 결과가
어긋났다. 지역명 변환처럼 규칙이 미묘한 것은 특히 위험해서 여기로 모았다.
"""
import csv
import os
import re
import unicodedata
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "datalab_raw")
DERIVED = os.path.join(ROOT, "data", "derived")
CACHE = os.path.join(ROOT, "data", "cache")
REPORTS = os.path.join(ROOT, "reports")
MAPPING = os.path.join(ROOT, "data", "mapping", "regions.csv")

# 앱 레포 경로. verify.py 와 places.py 가 .dc.html 을 읽어야 한다.
APP_REPO = os.environ.get("APP_REPO") or os.path.join(
    os.path.dirname(ROOT), "Tour-Navigator-App")
APP_HTML = os.path.join(APP_REPO, "Tour Planner.dc.html")


def NFC(s):
    """macOS는 한글 파일명을 자모 분리(NFD)로 저장한다. 비교 전에 반드시 합친다."""
    return unicodedata.normalize("NFC", s or "")


# ── 지역명 ────────────────────────────────────────────────────────────────
def load_region_map():
    """'경상북도 경주시' 같은 데이터랩 표기를 앱의 locKo('경주')로 바꾸는 표.

    match=prefix 는 첫 어절만 맞아도 적용한다(광역시는 자치구를 무시해야 하므로).
    match=exact 는 전체가 정확히 같을 때만. '경상북도'를 prefix로 두면
    '경상북도 경주시'가 '경북'이 되어버리기 때문에 구분이 필요하다.
    """
    prefix, exact = {}, {}
    if not os.path.exists(MAPPING):
        return prefix, exact
    for r in csv.DictReader(open(MAPPING, encoding="utf-8-sig")):
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


# ── 장소명 ────────────────────────────────────────────────────────────────
# 데이터랩은 지역명을 앞에 붙여 표기한다('경주불국사경내'). 앱은 안 붙인다.
REGION_PREFIX = ("경주", "거제", "서울", "제주", "부산", "영월", "서귀포")
# 데이터랩 쪽에만 붙는 꼬리표. 같은 장소를 다른 이름으로 만든다.
NAME_TAIL = ("경내", "관광지", "유원지", "일원", "지구")
# 포함관계여도 다른 장소인 경우. '산방산'과 '산방산탄산온천'은 별개다.
DIFFERENT_PLACE = ("온천", "호텔", "리조트", "컨벤션", "터미널", "골프",
                   "cc", "아울렛", "백화점", "휴게소")


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
        longer, shorter = (n, an) if len(n) > len(an) else (an, n)
        if any(w in longer.replace(shorter, "") for w in DIFFERENT_PLACE):
            continue
        return p, "partial"
    return None, None


# ── 데이터랩 원본 읽기 ─────────────────────────────────────────────────────
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


def read_csv(path):
    return list(csv.DictReader(open(path, encoding="utf-8-sig")))


def datalab_rows(region_raw, suffix):
    """특정 지역의 특정 CSV를 찾아 읽는다. 폴더가 여러 개로 쪼개져 있어도 된다."""
    if not os.path.isdir(RAW):
        return []
    for d in sorted(os.listdir(RAW)):
        p = os.path.join(RAW, d)
        if not os.path.isdir(p) or region_raw not in NFC(d):
            continue
        for f in os.listdir(p):
            if NFC(f).endswith(suffix):
                return read_csv(os.path.join(p, f))
    return []


# ── 통계 ─────────────────────────────────────────────────────────────────
def spearman(a, b):
    """순위상관. 동점은 평균순위로 처리한다.

    동점을 {값: 위치} dict로 처리하면 같은 값이 여러 개일 때 하나만 남고
    나머지가 사라져서, 상관계수가 실제보다 크게 나온다.
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
