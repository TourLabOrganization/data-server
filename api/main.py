# -*- coding: utf-8 -*-
"""data-server 추천 API.

    uvicorn api.main:app --host 0.0.0.0 --port 8000

파이프라인이 만들어 둔 JSON을 읽어 백엔드에 넘긴다. **계산은 이 안에서 하지 않는다.**
무거운 것(ETL·재분류·군집 학습)은 전부 배치로 끝나 있고, 여기서 도는 것은 요청마다
바뀌는 점수 정렬뿐이다 (5차원 내적).

산출물은 기동 시 한 번 읽어 메모리에 둔다. 파일이 바뀌면 컨테이너를 다시 띄운다 —
데이터랩은 월 단위 갱신이라 그 주기로 충분하다.
"""
import json
import os
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .scoring import CLUSTERS, rank_themes, region_adjust
from .schedule import (assign_days, day_windows, leg_info, stay_min, timeline)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DERIVED = os.path.join(ROOT, "data", "derived")
RECOMMEND = os.path.join(ROOT, "recommend", "data", "derived")

_store: dict = {}


def _load(path, required=True):
    if not os.path.exists(path):
        if required:
            raise RuntimeError(f"산출물이 없습니다: {path}\n"
                               f"`make all` 을 먼저 돌려 주세요.")
        return None
    return json.load(open(path, encoding="utf-8"))


@asynccontextmanager
async def lifespan(_app):
    """기동 시 산출물을 메모리에 올린다. 없으면 여기서 죽어야 한다 —
    반쪽짜리로 떠서 빈 응답을 주는 것보다 배포가 실패하는 편이 낫다."""
    _store["places"] = _load(os.path.join(DERIVED, "places.json"))
    _store["datalab"] = _load(os.path.join(DERIVED, "datalab.json"))
    _store["staytime"] = _load(os.path.join(DERIVED, "staytime.json"))
    _store["courses"] = _load(os.path.join(DERIVED, "courses.json"))
    # 추천은 원자료가 있어야 만들어지므로 없을 수도 있다. 그때는 해당 엔드포인트만 막는다.
    _store["calc2"] = _load(os.path.join(RECOMMEND, "calc2.json"), required=False)
    yield
    _store.clear()


app = FastAPI(
    title="Tour Navigator data-server",
    description="데이터랩·TourAPI 파이프라인 산출물과 테마 추천을 제공한다.",
    version="1.0.0",
    lifespan=lifespan,
)


# ── 헬스체크 ─────────────────────────────────────────────────────────────
@app.get("/health", summary="헬스체크")
def health():
    """배포 스크립트가 이걸 본다. 산출물이 다 올라왔는지까지 확인한다."""
    loaded = {k: _store.get(k) is not None
              for k in ("places", "datalab", "staytime", "courses", "calc2")}
    ready = loaded["places"] and loaded["datalab"] and loaded["courses"]
    return {"status": "ok" if ready else "degraded", "loaded": loaded}


# ── 파이프라인 산출물 ─────────────────────────────────────────────────────
@app.get("/v1/places", summary="장소 마스터 1,171곳")
def places(region: Optional[str] = None, course: Optional[str] = None):
    """`catApp`(앱 원본) 이 아니라 **`catFinal`** 을 쓴다. docs/contract.md 참고.

    코스에 속한 장소에는 `courses` 가 붙는다 — `[{courseId, title, seq}, …]`.
    한 장소가 여러 코스에 나올 수 있어 배열이다. **순서대로 걷는 화면을 만들 때는
    `/v1/courses` 를 쓰는 편이 낫다** — 그쪽이 코스 단위로 정렬돼 있다.
    """
    rows = _store["places"]["places"]
    membership = _course_membership()
    rows = [{**p, "courses": membership.get(p["id"], [])} for p in rows]
    if region:
        rows = [p for p in rows if p["region"] == region]
    if course:
        rows = [p for p in rows
                if any(c["courseId"] == course for c in p["courses"])]
    return {"count": len(rows), "places": rows}


def _course_membership():
    """{장소 마스터 id: [{courseId, title, seq}, …]}. 매 요청 만들기엔 가벼우나
    코스가 바뀌지 않으므로 한 번만 만들어 둔다."""
    if "membership" not in _store:
        m = {}
        for c in _store["courses"]["courses"]:
            for p in c["places"]:
                if p["placeId"]:
                    m.setdefault(p["placeId"], []).append(
                        {"courseId": c["courseId"], "title": c["title"],
                         "seq": p["seq"]})
        for v in m.values():
            v.sort(key=lambda x: (x["courseId"], x["seq"]))
        _store["membership"] = m
    return _store["membership"]


@app.get("/v1/courses", summary="영상 IP 코스와 순서대로의 장소")
def courses(courseId: Optional[str] = None, withPlaces: bool = True):
    """앱의 핵심 화면("영상 속 장소를 순서대로 따라 걷기")이 쓰는 데이터.

    장소는 `seq` 오름차순으로 들어 있다. `placeId` 로 장소 마스터와 이어진다
    (코스 파일과 마스터는 id 체계가 달라서 이름·좌표로 맞춘 것이다).
    목록만 필요하면 `withPlaces=false`.
    """
    rows = _store["courses"]["courses"]
    if courseId:
        rows = [c for c in rows if c["courseId"] == courseId]
        if not rows:
            raise HTTPException(
                404, f"없는 코스입니다: {courseId}. 가능한 값: "
                     f"{', '.join(c['courseId'] for c in _store['courses']['courses'])}")
    if not withPlaces:
        rows = [{k: v for k, v in c.items() if k != "places"} for c in rows]
    return {"count": len(rows), "courses": rows}


@app.get("/v1/tfi", summary="지역×테마 강도(TFI)")
def tfi(region: Optional[str] = None):
    """지역을 추가하면 **기존 지역 값도 바뀐다**(평균이 기준). 통째로 다시 읽을 것.

    `null` 은 '약하다'가 아니라 '모른다'는 뜻이다. 0으로 치환하지 말 것.
    """
    d = _store["datalab"]
    if region:
        if region not in d["tfi"]:
            raise HTTPException(404, f"TFI가 없는 지역입니다: {region}")
        return {"region": region, "themes": d["themes"],
                "tfi": d["tfi"][region], "detail": d["detail"][region]}
    return {"themes": d["themes"], "themeLabels": d["themeLabels"],
            "regions": d["regions"], "tfi": d["tfi"]}


@app.get("/v1/staytime", summary="지역 체류시간과 전국 대비 지수")
def staytime(region: Optional[str] = None):
    """`index`(전국 평균 대비 배수)만 쓰는 것을 권한다.

    `stayMinutes` 는 지역 1회 방문 총량(분)이고 places 의 `stayMin` 은 장소당
    관람시간이다. **단위가 다르니 나누거나 빼지 말 것.**
    """
    rows = _store["staytime"]["regions"]
    if region:
        rows = [r for r in rows if r["region"] == region]
        if not rows:
            raise HTTPException(404, f"체류시간 데이터가 없는 지역입니다: {region}")
    return {"latestYear": _store["staytime"]["latestYear"],
            "source": _store["staytime"]["source"], "regions": rows}


# ── 일정 ─────────────────────────────────────────────────────────────────
class ItineraryRequest(BaseModel):
    courseId: Optional[str] = Field(
        None, description="코스 id. 주면 그 코스의 장소를 seq 순서로 쓴다",
        examples=["jeju-k-drama-route"])
    placeIds: Optional[List[str]] = Field(
        None, description="장소 id 목록. courseId 대신 쓴다. **주는 순서가 곧 동선**")
    days: int = Field(1, ge=1, le=10, description="여행 일수")
    mode: str = Field("transit", description="이동수단: transit · driving · own")
    depTime: str = Field("08:00", description="출발지 출발 시각")
    retTime: str = Field("19:00", description="여행지 출발(귀가) 시각")
    accessMin: int = Field(
        0, ge=0, description="출발지→지역 관문 광역 이동(분). 첫날 창을 줄인다")


@app.post("/v1/itinerary", summary="코스 → 일자별 도착·출발 시각")
def itinerary(req: ItineraryRequest):
    """장소 순서 + 여행 조건 → "09:00–10:10" 형태의 일정.

    계산은 `api/schedule.py` 가 한다. 앱 레포의 `체류시간 산정/stay_schedule.js`
    를 옮긴 것이고, 원본과 같은 값이 나오는 것을 대조로 확인했다.

    **근거가 있는 것은 이동시간 쪽이다** — 한국도로공사 고속도로 표정속도 92km/h,
    KTX 200km/h, 고속버스 110km/h. 장소별 체류시간은 편집 추정치다.

    창(하루 720분)을 넘기는 경유지는 다음 날로 넘어가고, 마지막 날에도 못 들어가면
    잘린다(`dropped`).
    """
    if not req.courseId and not req.placeIds:
        raise HTTPException(400, "courseId 또는 placeIds 중 하나는 있어야 합니다.")

    if req.courseId:
        hit = [c for c in _store["courses"]["courses"]
               if c["courseId"] == req.courseId]
        if not hit:
            raise HTTPException(404, f"없는 코스입니다: {req.courseId}")
        items = list(hit[0]["places"])          # 이미 seq 순
    else:
        master = {p["id"]: p for p in _store["places"]["places"]}
        missing = [i for i in req.placeIds if i not in master]
        if missing:
            raise HTTPException(404, f"없는 장소 id: {', '.join(missing[:5])}")
        items = [master[i] for i in req.placeIds]   # 준 순서가 곧 동선

    # 체류시간이 0인 장소(숙소 등)는 일정에 넣지 않는다 — 앱과 같은 규칙
    items = [p for p in items if stay_min(p) > 0]
    if not items:
        raise HTTPException(400, "체류시간이 있는 장소가 없습니다.")

    windows = day_windows(req.days, req.depTime, req.retTime, req.accessMin)
    leg = lambda a, b: leg_info(a, b, req.mode)
    buckets, keep = assign_days(items, windows, leg)
    rows = timeline(items, buckets, leg, req.depTime, req.accessMin)

    move_sum = sum(r["moveMin"] for r in rows)
    stay_sum = sum(r["stayMin"] for r in rows)
    return {
        "courseId": req.courseId,
        "days": req.days, "mode": req.mode,
        "dayWindows": windows,
        "placed": keep, "dropped": len(items) - keep,
        "totals": {"stayMin": stay_sum, "moveMin": move_sum,
                   "waitMin": sum(r["waitMin"] for r in rows),
                   "totalMin": stay_sum + move_sum},
        "schedule": rows,
    }


# ── 추천 ─────────────────────────────────────────────────────────────────
class RecommendRequest(BaseModel):
    cluster: str = Field(..., description="군집 C1~C10", examples=["C4"])
    interests: List[int] = Field(
        default_factory=list,
        description="관심 카테고리 인덱스 (cats 기준 0~4)", examples=[[0, 1]])
    night: bool = Field(False, description="야경 선호")
    region: Optional[str] = Field(
        None,
        description="여행 지역명. 주면 그 지역의 데이터랩 TFI를 지역 보정(±0.05)에 "
                    "반영한다. /v1/tfi 의 regions 에 있는 이름이어야 하고, 없으면 "
                    "400 을 돌려준다. 생략하면 보정 없이(0) 계산한다.",
        examples=["경주"])


@app.get("/v1/personas", summary="미리 계산해 둔 사용자 유형 8종")
def personas():
    """`calc2.py` 가 배치로 계산해 둔 결과. 설문 없이 바로 보여줄 때 쓴다."""
    c = _store["calc2"]
    if not c:
        raise HTTPException(503, "calc2.json 이 없습니다. recommend/run_all.py 를 돌려 주세요.")
    return {"cats": c["cats"], "clusters": c["userc"], "rankings": c["U"]}


@app.post("/v1/recommend", summary="설문 응답 → 테마 추천 순위")
def recommend(req: RecommendRequest):
    """점수 = fit + interest + region.

    **`region` 항이 한국관광 데이터랩이 추천에 들어가는 지점이다.**

      fit       군집 선호 × 코스 구성      (국민여행조사·외래관광객조사 기반)
      interest  관심 카테고리 보너스        (사용자 입력)
      region    그 지역의 테마 강도 TFI     ← 데이터랩 (카드소비·통신 방문 실측)

    앞의 둘은 "우리가 코스에 무엇을 넣었나"와 "사용자가 무엇을 골랐나"라서 외부
    근거가 없다. `region` 만이 외부 실측이다 — "이 코스가 역사 40%인데 그 지역이
    실제로 역사 강세인가"를 데이터랩으로 확인해 ±0.05 를 더한다.

    **`region` 을 주지 않으면 데이터랩이 점수에 들어가지 않는다.** 응답의
    `regionApplied` 와 `sources` 로 확인할 수 있다.
    """
    c = _store["calc2"]
    if not c:
        raise HTTPException(503, "calc2.json 이 없습니다. recommend/run_all.py 를 돌려 주세요.")
    if req.cluster not in CLUSTERS:
        raise HTTPException(400, f"군집은 {CLUSTERS[0]}~{CLUSTERS[-1]} 중 하나여야 합니다.")

    region_adj, coverage = None, None
    if req.region:
        tfi_all = _store["datalab"]["tfi"]
        if req.region not in tfi_all:
            # 조용히 0으로 넘어가면 호출한 쪽이 "반영됐다"고 오해한다. 명시적으로 막는다.
            raise HTTPException(
                400, f"TFI가 없는 지역입니다: {req.region}. "
                     f"가능한 지역: {', '.join(sorted(tfi_all))}")
        tfi = tfi_all[req.region]
        region_adj, coverage = {}, {}
        for theme, p in c["P"].items():
            adj, den = region_adjust(c["cats"], p["share"], tfi)
            region_adj[theme] = adj
            coverage[theme] = round(den, 4)

    themes = rank_themes(c, req.cluster, req.interests, req.night, region_adj)
    if coverage:
        for t in themes:
            # 코스 구성 중 TFI로 덮인 비율. 해양·자연은 TFI 축이 없어 빠진다.
            t["regionCoverage"] = coverage[t["theme"]]

    # 이 점수에 무엇이 들어갔는지 응답에 남긴다. 호출하는 쪽이 "데이터랩이
    # 반영됐나"를 되묻지 않아도 되고, 심사 때 근거로도 쓸 수 있다.
    sources = ["국민여행조사", "외래관광객조사"]
    if region_adj is not None:
        sources.append("한국관광 데이터랩 (지역×테마 강도 TFI)")

    return {"cluster": req.cluster, "cats": c["cats"],
            "region": req.region,
            "regionApplied": region_adj is not None,
            "sources": sources,
            "themes": themes}
