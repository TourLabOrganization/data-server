# -*- coding: utf-8 -*-
"""영상 IP 코스 5개 → 순서가 있는 장소 목록 JSON.

    python -m pipeline.courses

앱의 핵심 화면이 "영상 속 장소를 순서대로 따라 걷기"라, 코스마다 **장소의 순번**이
있어야 한다. 그 정보는 `Tour Planner.dc.html`(전체 장소 목록)이 아니라 코스별
`.dc.html` 5개에 따로 들어 있다.

  Tour Planner.dc.html   지역별 전체 장소 — id 가 gj1·js1…  (places.py 가 읽는다)
  Jeju K-Drama Route     그 코스의 순서    — id 가 jd1·jd2…  (여기서 읽는다)

id 체계가 서로 달라서 같은 장소도 id 가 다르다. 이름·좌표로 이어 붙인다.

산출: data/derived/courses.json
"""
import json
import os
import re
import sys

from .common import APP_REPO, DERIVED, NFC, norm_name

# (파일명, 코스 표시 이름). 파일명이 곧 앱의 화면 단위다.
COURSE_FILES = [
    ("Kings Warden Route", "왕과 사는 남자"),
    ("KPop Demon Hunters Route", "케이팝 데몬 헌터스"),
    ("RESCENE Route", "RESCENE"),
    ("Jeju K-Drama Route", "제주 K-Drama"),
    ("Busan Cinema Route", "부산 영화 기행"),
]

# 코스 파일 포맷이 바뀌면 조용히 일부만 빠지지 않도록 최소 개수를 건다.
MIN_PER_COURSE = 3


def _place_blocks(src):
    """DATA 안의 **모든** 지역 블록에서 places:[ … ] 본문을 꺼낸다.

    코스가 한 지역에만 있는 줄 알고 첫 블록만 읽었더니 RESCENE 이 7곳만 잡혔다.
    실제로는 경주·거제·전국 3개 블록에 걸쳐 있다. 코스는 여러 지역을 지날 수 있다.

    DATA 에는 장소 블록 말고 화면 문구 블록(ui·sub·all…)도 같이 있다.
    `ko:` 로 시작하고 그 안에 `places:[` 가 있는 것만 장소 블록이다.
    """
    at = src.find("const DATA")
    if at < 0:
        return []
    out = []
    for m in re.finditer(r"\n  (\w+):\s*\{ko:'([^']*)'", src[at:]):
        head = at + m.end()
        # 다음 블록이 시작되기 전에 places:[ 가 있어야 장소 블록이다
        nxt = src.find("\n  ", head)
        try:
            s0 = src.index("places:[", head) + len("places:[")
        except ValueError:
            continue
        if nxt != -1 and s0 > src.find("places:[", head) + 1000000:
            continue
        depth, i = 1, s0
        while depth and i < len(src):
            if src[i] == "[":
                depth += 1
            elif src[i] == "]":
                depth -= 1
            i += 1
        out.append((m.group(1), NFC(m.group(2)), src[s0:i - 1]))
    return out


def parse_course(path):
    src = open(path, encoding="utf-8").read()
    out = []
    for block_key, block_ko, body in _place_blocks(src):
      for rec in re.findall(r"\{[^{}]*\}", body):
          def s(field):
              m = re.search(rf"\b{field}:'((?:[^'\\]|\\.)*)'", rec)
              return NFC(m.group(1)) if m else None

          def n(field):
              m = re.search(rf"\b{field}:(-?[\d.]+)", rec)
              return float(m.group(1)) if m else None

          if not (s("id") and s("ko")) or n("n") is None:
              continue
          out.append({
              "seq": int(n("n")),
              "block": block_key,
              "coursePlaceId": s("id"),
              "nameKo": s("ko"),
              "nameEn": s("en"),
              "catApp": s("cat"),
              "lat": n("lat"),
              "lng": n("lng"),
              "stayMin": int(n("min")) if n("min") is not None else None,
              "hours": s("hrs"),
              "youtubeId": s("yt"),
              # 영상 정보. 코스 파일에만 있고 장소 마스터에는 없다
              "videoTitle": s("chan"),
              "sceneKo": s("vt"),
          })
    out.sort(key=lambda p: p["seq"])
    return out


def link_to_master(course_places, master):
    """코스 장소를 장소 마스터의 id 로 이어 붙인다.

    코스 파일과 장소 마스터는 id 체계가 다르다(jd1 vs js1). 이름을 정규화해
    맞추고, 같은 이름이 여러 지역에 있을 수 있으니 좌표가 5km 안인지 본다.
    """
    idx = {}
    for m in master:
        idx.setdefault(norm_name(m["nameKo"]), []).append(m)

    linked = 0
    for p in course_places:
        p["placeId"] = None
        p["region"] = None
        for m in idx.get(norm_name(p["nameKo"]), []):
            if p["lat"] is None or m["lat"] is None:
                continue
            km = (((p["lng"] - m["lng"]) * 88.9) ** 2
                  + ((p["lat"] - m["lat"]) * 111.0) ** 2) ** .5
            if km <= 5.0:
                p["placeId"] = m["id"]
                p["region"] = m["region"]
                # 마스터 쪽 교정 카테고리를 그대로 쓴다. 코스 파일의 cat 은 원본이다
                p["catFinal"] = m.get("catFinal") or m["catApp"]
                p["catFinalKo"] = m.get("catFinalKo")
                linked += 1
                break
        p.setdefault("catFinal", p["catApp"])
        p.setdefault("catFinalKo", None)
    return linked


def main():
    master_path = os.path.join(DERIVED, "places.json")
    if not os.path.exists(master_path):
        sys.exit("data/derived/places.json 이 없습니다. "
                 "먼저 `python -m pipeline.places` 를 돌려 주세요.")
    master = json.load(open(master_path, encoding="utf-8"))["places"]

    courses, total, total_linked = [], 0, 0
    for fname, title in COURSE_FILES:
        path = os.path.join(APP_REPO, f"{fname}.dc.html")
        if not os.path.exists(path):
            print(f"  ⚠️ 코스 파일 없음: {fname}.dc.html — 건너뜀")
            continue
        places = parse_course(path)
        if len(places) < MIN_PER_COURSE:
            sys.exit(f"{fname}: 장소를 {len(places)}곳만 찾았습니다. "
                     f"코스 파일 포맷이 바뀐 것 같습니다.")
        linked = link_to_master(places, master)
        regions = sorted({p["region"] for p in places if p["region"]})
        courses.append({
            "courseId": fname.replace(" ", "-").lower(),
            "title": title,
            "file": f"{fname}.dc.html",
            "regions": regions,
            "count": len(places),
            "stayMinSum": sum(p["stayMin"] or 0 for p in places),
            "places": places,
        })
        total += len(places)
        total_linked += linked
        print(f"  {title:18} 장소 {len(places):3}곳 · 마스터 연결 {linked:3}곳 "
              f"· 지역 {','.join(regions) if regions else '—'}")

    os.makedirs(DERIVED, exist_ok=True)
    dst = os.path.join(DERIVED, "courses.json")
    json.dump({"count": len(courses), "courses": courses},
              open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n코스 {len(courses)}개 · 장소 {total}곳 "
          f"· 마스터 연결 {total_linked}곳 ({total_linked/total*100:.0f}%)")
    print(f"완료 → {dst}")


if __name__ == "__main__":
    main()
