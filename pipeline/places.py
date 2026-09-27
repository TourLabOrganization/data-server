# -*- coding: utf-8 -*-
"""앱의 .dc.html 에 하드코딩된 장소 3,118곳 → 장소 마스터 JSON.

    python -m pipeline.places

앱은 정적 HTML 한 파일 안에 장소를 JS 객체 리터럴로 들고 있다.
백엔드가 이걸 DB에 적재하려면 먼저 구조화된 형태로 꺼내야 한다. 그 추출이
이 스크립트다.

JS 리터럴이라 JSON 파서를 쓸 수 없고, 앱을 실행하지 않고 읽어야 하므로
정규식으로 파싱한다. 앱의 포맷이 바뀌면 여기가 먼저 깨지도록 장소 수를
검증해서, 조용히 일부만 빠지는 일이 없게 한다.

산출: data/derived/places.json
"""
import json
import os
import re
import sys

from .common import APP_HTML, DERIVED, NFC

# 앱이 쓰는 카테고리. 재분류 전 원본 값이다.
APP_CATS = ("heal", "herit", "activity", "food", "sea", "stay")

# 앱 화면(Tour Planner.dc.html 의 CATS)이 쓰는 한글 카테고리명. 프론트가 그대로
# 띄우는 값이라 화면 표기를 정본으로 삼는다. 팀원 추천 코드
# (테마 추천 알고리즘/src/classify.py)는 예전 표기('역사·문화' 등)를 쓰는데,
# 코드값(herit·heal…)이 같아서 붙이는 데는 지장이 없다.
CAT_KO = {"herit": "문화유산·전통체험", "heal": "힐링·생태·체험",
          "activity": "테마파크·액티비티", "food": "로컬상권·먹거리",
          "sea": "해양·자연경관", "stay": "숙박"}

# 앱 포맷이 바뀌어 파싱이 깨지면 알아차려야 한다. 이보다 적게 나오면 실패시킨다.
# 앱은 2026-09-27 기준 3,118곳이다 (앱 레포 DATA.md). 여유를 두고 3,000 으로 잡는다.
MIN_EXPECTED = 3000


def _blocks(src):
    """DATA 안의 지역 블록들을 {키: (지역명, 지역명(영문), places 배열 본문)} 으로 꺼낸다.

    'seoul:' 'jeju:' 같은 키는 ORIGINS·REGION_HUB 같은 다른 상수에도 있어서,
    DATA 밖에서 먼저 걸리면 엉뚱한 블록을 읽는다. DATA 시작점 뒤에서만 찾는다.
    """
    at = src.find("const DATA")
    if at < 0:
        sys.exit("앱 파일에서 'const DATA' 를 찾지 못했습니다. 포맷이 바뀐 것 같습니다.")
    out = {}
    for m in re.finditer(r"\n  (\w+):\s*\{ko:'([^']*)',\s*en:'([^']*)'", src[at:]):
        try:
            s = src.index("places:[", at + m.end()) + len("places:[")
        except ValueError:
            continue                        # places 가 없는 블록(ui 등)은 건너뛴다
        depth, i = 1, s
        while depth and i < len(src):
            if src[i] == "[":
                depth += 1
            elif src[i] == "]":
                depth -= 1
            i += 1
        out[m.group(1)] = (NFC(m.group(2)), m.group(3), src[s:i - 1])
    return out


def corrections():
    """TourAPI 재분류에서 '반영' 판정이 난 것만 {장소id: 카테고리} 로.

    앱 HTML은 건드리지 않고 여기서 덧씌운다. 교정 근거가 data-server 안에만
    있으므로, 무엇을 왜 바꿨는지 되짚을 수 있다.

    categories.json 이 없어도(재분류 전) 정상 동작해야 하므로 빈 값을 돌려준다.
    """
    path = os.path.join(DERIVED, "categories.json")
    if not os.path.exists(path):
        return {}
    rows = json.load(open(path, encoding="utf-8"))["places"]
    return {r["id"]: r["catOfficial"] for r in rows if r.get("apply")}


def pop_ranks():
    """데이터랩 인기관광지 순위 {장소id: 순위}. `make popularity` 가 만든다.

    **배지용이다.** 받아 둔 지역만 순위가 있어서 5% 남짓에만 값이 붙는다.
    목록 정렬에 쓰면 나머지가 전부 한 덩어리로 뒤에 밀린다 — popularity.py 주석 참고.
    """
    path = os.path.join(DERIVED, "popularity.json")
    if not os.path.exists(path):
        return {}
    return json.load(open(path, encoding="utf-8"))["ranks"]


def extract():
    if not os.path.exists(APP_HTML):
        sys.exit(f"앱 파일을 찾을 수 없습니다: {APP_HTML}\n"
                 f"APP_REPO 환경변수로 앱 레포 경로를 주세요.")
    src = open(APP_HTML, encoding="utf-8").read()

    places = []
    for key, (region_ko, region_en, body) in _blocks(src).items():
        for rec in re.findall(r"\{[^{}]*\}", body):
            def s(field):
                m = re.search(rf"\b{field}:'((?:[^'\\]|\\.)*)'", rec)
                return NFC(m.group(1)) if m else None

            def n(field):
                m = re.search(rf"\b{field}:(-?[\d.]+)", rec)
                return float(m.group(1)) if m else None

            def flag(field):
                """앱은 참일 때만 `k100:1` 처럼 적는다. 없으면 거짓이다."""
                return bool(re.search(rf"\b{field}:1\b", rec))

            if not (s("id") and s("ko")):
                continue                    # 장소가 아닌 객체(옵션 등)
            places.append({
                "id": s("id"),
                "block": key,
                # 프론트가 언어를 바꿔도 같은 순서로 그릴 수 있게 고정 순번을 준다.
                # 이름순으로 정렬하면 한국어/영어에서 순서가 달라진다.
                "order": len(places),
                # 앱 목록에 붙는 번호. 목록외(off) 장소는 번호가 없어 None 이다
                "listNo": int(n("n")) if n("n") is not None else None,
                "nameKo": s("ko"),
                "nameEn": s("en"),
                # 'nation' 블록은 장소마다 locKo 를 들고 있고, 지역 블록은 블록 이름이 곧 지역이다
                "region": s("locKo") or (None if key == "nation" else region_ko),
                "regionEn": s("locEn") or (None if key == "nation" else region_en),
                "catApp": s("cat"),
                "lat": n("lat"),
                "lng": n("lng"),
                "stayMin": int(n("min")) if n("min") is not None else None,
                "hours": s("hrs"),
                "youtubeId": s("yt"),
                "sourceKo": s("srcKo"),
                "sourceEn": s("srcEn"),
                # 장소 상세에 띄우는 설명. 한국어는 전부 있고 영어는 일부만 있다
                "descKo": s("bKo"),
                "descEn": s("bEn"),
                "imageUrl": s("img"),
                "imageCredit": s("imgCredit"),
                "kakaoUrl": s("url"),
                # 배지 — 한국관광 100선 · 유네스코 · 열린관광지(무장애)
                "k100": flag("k100"),
                "unesco": flag("un"),
                "barrierFree": flag("bf"),
                # 관광특구·관광단지·지정관광지 문구. 해당 없으면 None
                "zone": s("vz"),
                # 이 장소가 어디서 들어왔는지 — 시티투어 경유지 / 공사 연관관광지
                "cityTour": flag("ct"),
                "related": flag("rs"),
                # 앱이 목록에서 내려둔 장소. 추천 순서 계산에서 뒤로 민다
                "inactive": "off:true" in rec,
            })

    if len(places) < MIN_EXPECTED:
        sys.exit(f"장소를 {len(places)}곳만 찾았습니다(기대 {MIN_EXPECTED}곳 이상).\n"
                 f"앱의 HTML 포맷이 바뀌어 파싱이 깨졌을 가능성이 큽니다.")
    return places


def main():
    places = extract()

    fix = corrections()
    pop = pop_ranks()
    for p in places:
        # 데이터랩 인기관광지 순위. 없으면 None — 0 으로 채우지 않는다
        p["popRank"] = pop.get(p["id"])
        official = fix.get(p["id"])
        # catApp   앱 HTML 원본값 (손으로 넣은 값)
        # catFinal 백엔드가 써야 할 값 — 교정이 있으면 교정본
        p["catFinal"] = official or p["catApp"]
        p["catSource"] = "tourapi" if official else "app"
        p["catFinalKo"] = CAT_KO.get(p["catFinal"], p["catFinal"])

    bad_cat = sorted({p["catApp"] for p in places} - set(APP_CATS) - {None})
    no_coord = [p for p in places if p["lat"] is None or p["lng"] is None]
    no_region = [p for p in places if not p["region"]]

    os.makedirs(DERIVED, exist_ok=True)
    dst = os.path.join(DERIVED, "places.json")
    json.dump({"count": len(places), "places": places},
              open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    regions = {p["region"] for p in places if p["region"]}
    n_fix = sum(1 for p in places if p["catSource"] == "tourapi")
    print(f"장소 {len(places)}곳 / 지역 {len(regions)}곳")
    for label, field in (("앱 원본", "catApp"), ("교정 후", "catFinal")):
        cats = {}
        for p in places:
            cats[p[field]] = cats.get(p[field], 0) + 1
        print(f"  {label}: " + str(dict(sorted(cats.items(), key=lambda x: -x[1]))))
    print(f"  TourAPI 교정 적용 {n_fix}곳")
    n_pop = sum(1 for p in places if p["popRank"])
    print(f"  데이터랩 인기관광지 순위 {n_pop}곳 (배지용)")
    if not pop:
        print("  ⚠️ data/derived/popularity.json 이 없습니다. popRank 가 전부"
              " 비어 배지가 사라집니다.\n"
              "     `make popularity` 를 먼저 돌리세요 (데이터랩 다운로드 필요).")
    if not fix:
        print("  ⚠️ data/derived/categories.json 이 없습니다. catFinal 이 앱 원본값"
              " 그대로입니다.\n"
              "     교정을 반영하려면 `make tourapi` 를 먼저 돌리세요"
              " (TOURAPI_KEY 필요).")
    if bad_cat:
        print(f"  ⚠️ 모르는 카테고리 값: {bad_cat}")
    if no_coord:
        print(f"  ⚠️ 좌표 없는 장소 {len(no_coord)}곳: "
              f"{[p['nameKo'] for p in no_coord][:5]}")
    if no_region:
        print(f"  ⚠️ 지역 없는 장소 {len(no_region)}곳: "
              f"{[p['nameKo'] for p in no_region][:5]}")
    print(f"\n완료 → {dst}")


if __name__ == "__main__":
    main()
