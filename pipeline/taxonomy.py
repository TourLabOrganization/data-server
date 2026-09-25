# -*- coding: utf-8 -*-
"""분류 체계 한 곳. 앱 · TourAPI · 데이터랩을 같은 축 위에 올린다.

이 파일이 이 레포의 핵심 가정을 담고 있다.

  데이터랩 '인기관광지'의 `분류` 컬럼과 TourAPI 의 분류체계(`lclsSystm`)는
  **같은 체계다.** 구분자만 다르다 ('자연경관(하천/해양)' vs '자연경관(하천‧해양)').

그래서 앱 장소를 TourAPI 로 재분류하면, 앱과 데이터랩을 같은 기준으로 비교할 수
있게 된다. 두 쪽이 이 파일의 매핑 하나를 공유한다.

  tourapi.py  : 앱 장소 → TourAPI 조회 → lclsSystm2/3 → 앱 카테고리
  datalab.py  : 데이터랩 분류명 → lclsSystm2 → 앱 카테고리

앱 카테고리는 heal(힐링·생태·체험) · herit(역사·문화유산) · activity · food ·
sea(바다) · stay(숙박) 6종이고, None 은 '앱이 다루지 않는 대상'이다.
"""
import json
import os
import re

from .common import NFC

CODES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "mapping", "tourapi_codes.json")


# ── 중분류(lclsSystm2) → 앱 카테고리 ──────────────────────────────────────
# None 은 앱이 다루지 않는 대상(쇼핑시설·교통시설)이라는 뜻이다.
CAT_BY_MID = {
    # 숙박
    "AC01": "stay", "AC02": "stay", "AC03": "stay", "AC04": "stay",
    "AC05": "stay", "AC06": "stay",
    # 체험관광 — 앱의 heal 은 '힐링·생태·체험'이라 웰니스·산사체험이 여기 붙는다
    "EX01": "activity", "EX02": "activity", "EX03": "activity",
    "EX04": "heal", "EX05": "heal", "EX06": "activity", "EX07": "activity",
    # 음식
    "FD01": "food", "FD02": "food", "FD03": "food", "FD04": "food",
    "FD05": "food",
    # 역사관광
    "HS01": "herit", "HS02": "herit", "HS03": "herit", "HS04": "herit",
    # 레저스포츠 — LS02(수상)는 바다와 민물이 섞여 있다. 기본은 activity 로 두고
    # 바다인 것만 소분류에서 sea 로 올린다. 통째로 sea 로 두면 대청호 민물낚시나
    # 내린천 래프팅까지 바다가 된다.
    "LS01": "activity", "LS02": "activity", "LS03": "activity",
    "LS04": "activity",
    # 자연관광 — NA02 는 강·호수와 해변이 섞여 있어 소분류로 가른다
    "NA01": "heal", "NA02": "heal", "NA03": "heal", "NA04": "heal",
    "NA05": "heal",
    # 쇼핑 — 앱에는 쇼핑 카테고리가 없다. 시장만 food 로 받는다
    "SH01": None, "SH02": None, "SH03": None, "SH04": None,
    "SH05": "activity", "SH06": "food", "SH07": None,
    # 문화관광
    "VE01": "activity", "VE02": "activity", "VE03": "heal", "VE04": "herit",
    "VE05": "activity", "VE06": "activity", "VE07": "herit", "VE08": "activity",
    "VE09": "herit", "VE10": "activity", "VE11": None, "VE12": "activity",
}

# 소분류(lclsSystm3)가 중분류와 다른 판정을 내려야 하는 경우.
# 바다 관련이 핵심이다 — 앱의 sea 는 TourAPI 대분류에 대응물이 없고,
# NA02(하천‧해양)와 VE01(랜드마크), LS02(수상레저) 안에 흩어져 있다.
CAT_BY_SUB = {
    "NA020100": "heal",   # 강
    "NA020200": "heal",   # 호수
    "NA020300": "heal",   # 저수지
    "NA020400": "heal",   # 연못·늪
    "NA020500": "sea",    # 섬
    "NA020600": "sea",    # 염전
    "NA020700": "sea",    # 항구/포구
    "NA020800": "sea",    # 해안절경
    "NA020900": "sea",    # 해변. 해수욕장
    "VE010800": "sea",    # 등대
    "VE010700": "heal",   # 댐
    "LS020300": "sea",    # 요트
    "LS020400": "sea",    # 스노쿨링/스킨스쿠버다이빙
    "LS020600": "sea",    # 바다낚시
    "LS021300": "sea",    # 패러세일
}


def to_app_cat(m2, m3=""):
    """TourAPI 중·소분류 → 앱 카테고리. 소분류가 있으면 그쪽을 우선한다."""
    if m3 in CAT_BY_SUB:
        return CAT_BY_SUB[m3]
    return CAT_BY_MID.get(m2)


# ── 데이터랩 분류명 → 중분류 코드 ─────────────────────────────────────────
# 데이터랩에만 있고 TourAPI 중분류에는 없는 표기. 확인 후 손으로 붙였다.
DATALAB_ALIAS = {
    "자연관광(산)": "NA01",       # '자연경관(산)'의 표기 흔들림
    "기타레저스포츠": "LS04",      # 레저스포츠 계열 기타
    "데이트코스": None,           # 추천코스라 장소가 아니다. 모수에서 뺀다
    "기타관광": None,             # 데이터랩 고유 catch-all. 무엇인지 알 수 없다
}


# 데이터랩은 중분류까지만 주므로 '육상레저스포츠' 안에서 골프장을 뗄 수 없다.
# 그런데 지역에 따라 이게 그 분류의 절반을 넘는다(경주 28곳 중 13곳). 앱은
# 골프장을 다루지 않으므로, 그대로 두면 '경주는 체험·활동 강세'라는 잘못된
# 결론이 나온다. 이름으로 거른다 — 정밀하지는 않지만 보고 가능한 기준이다.
GOLF_PATTERN = re.compile(r"골프|컨트리클럽|(?:^|[^A-Za-z])(?:CC|GC)$", re.I)


def is_golf(name):
    return bool(GOLF_PATTERN.search(NFC(name).replace(" ", "")))


def _norm(s):
    """분류명 비교용. 구분자 차이('/' vs '‧')와 공백·괄호를 지운다."""
    return re.sub(r"[\s/‧·.\-()]", "", NFC(s)).lower()


def _load_mid_index():
    codes = json.load(open(CODES_PATH, encoding="utf-8"))
    idx = {}
    for big in codes.values():
        for code, mid in big["children"].items():
            idx[_norm(mid["name"])] = code
    return idx


_MID_INDEX = None


def datalab_class_to_mid(name):
    """데이터랩 '분류' 값 → TourAPI 중분류 코드.

    돌려주는 값이 None 이면 두 가지 경우다. 구분이 필요하면
    `name in DATALAB_ALIAS` 로 확인한다.
      - 별칭 표에 None 으로 적힌 것 → 의도적으로 제외하는 대상
      - 별칭 표에도 없는 것        → 모르는 값. 호출한 쪽이 보고해야 한다
    """
    global _MID_INDEX
    n = NFC(name).strip()
    if n in DATALAB_ALIAS:
        return DATALAB_ALIAS[n]
    if _MID_INDEX is None:
        _MID_INDEX = _load_mid_index()
    return _MID_INDEX.get(_norm(n))


def datalab_class_to_cat(name):
    """데이터랩 '분류' 값 → 앱 카테고리.

    데이터랩은 **중분류까지만** 준다. 그래서 NA02(자연경관 하천‧해양)를
    바다와 내륙으로 가를 수 없고, 전부 heal 로 떨어진다. 앱 쪽은 TourAPI 에서
    소분류를 받아오므로 sea 를 따로 뗄 수 있다 — 이 비대칭을 기억해야 한다.
    """
    mid = datalab_class_to_mid(name)
    return to_app_cat(mid) if mid else None
