# -*- coding: utf-8 -*-
"""앱의 .dc.html 에 하드코딩된 장소 1,171곳 → 장소 마스터 JSON.

    python -m pipeline.places

앱은 정적 HTML 한 파일(24,000줄) 안에 장소를 JS 객체 리터럴로 들고 있다.
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

# 앱 포맷이 바뀌어 파싱이 깨지면 알아차려야 한다. 이보다 적게 나오면 실패시킨다.
MIN_EXPECTED = 1000


def _blocks(src):
    """DATA 안의 지역 블록들을 {키: (지역명, places 배열 본문)} 으로 꺼낸다.

    'seoul:' 'jeju:' 같은 키는 ORIGINS·REGION_HUB 같은 다른 상수에도 있어서,
    DATA 밖에서 먼저 걸리면 엉뚱한 블록을 읽는다. DATA 시작점 뒤에서만 찾는다.
    """
    at = src.find("const DATA")
    if at < 0:
        sys.exit("앱 파일에서 'const DATA' 를 찾지 못했습니다. 포맷이 바뀐 것 같습니다.")
    out = {}
    for m in re.finditer(r"\n  (\w+):\s*\{ko:'([^']*)'", src[at:]):
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
        out[m.group(1)] = (NFC(m.group(2)), src[s:i - 1])
    return out


def extract():
    if not os.path.exists(APP_HTML):
        sys.exit(f"앱 파일을 찾을 수 없습니다: {APP_HTML}\n"
                 f"APP_REPO 환경변수로 앱 레포 경로를 주세요.")
    src = open(APP_HTML, encoding="utf-8").read()

    places = []
    for key, (region_ko, body) in _blocks(src).items():
        for rec in re.findall(r"\{[^{}]*\}", body):
            def s(field):
                m = re.search(rf"\b{field}:'((?:[^'\\]|\\.)*)'", rec)
                return NFC(m.group(1)) if m else None

            def n(field):
                m = re.search(rf"\b{field}:(-?[\d.]+)", rec)
                return float(m.group(1)) if m else None

            if not (s("id") and s("ko")):
                continue                    # 장소가 아닌 객체(옵션 등)
            places.append({
                "id": s("id"),
                "block": key,
                "nameKo": s("ko"),
                "nameEn": s("en"),
                # 'nation' 블록은 장소마다 locKo 를 들고 있고, 지역 블록은 블록 이름이 곧 지역이다
                "region": s("locKo") or (None if key == "nation" else region_ko),
                "catApp": s("cat"),
                "lat": n("lat"),
                "lng": n("lng"),
                "stayMin": int(n("min")) if n("min") is not None else None,
                "hours": s("hrs"),
                "youtubeId": s("yt"),
                "sourceKo": s("srcKo"),
            })

    if len(places) < MIN_EXPECTED:
        sys.exit(f"장소를 {len(places)}곳만 찾았습니다(기대 {MIN_EXPECTED}곳 이상).\n"
                 f"앱의 HTML 포맷이 바뀌어 파싱이 깨졌을 가능성이 큽니다.")
    return places


def main():
    places = extract()

    bad_cat = sorted({p["catApp"] for p in places} - set(APP_CATS) - {None})
    no_coord = [p for p in places if p["lat"] is None or p["lng"] is None]
    no_region = [p for p in places if not p["region"]]

    os.makedirs(DERIVED, exist_ok=True)
    dst = os.path.join(DERIVED, "places.json")
    json.dump({"count": len(places), "places": places},
              open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    regions = {p["region"] for p in places if p["region"]}
    print(f"장소 {len(places)}곳 / 지역 {len(regions)}곳")
    cats = {}
    for p in places:
        cats[p["catApp"]] = cats.get(p["catApp"], 0) + 1
    print("  앱 카테고리:", dict(sorted(cats.items(), key=lambda x: -x[1])))
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
