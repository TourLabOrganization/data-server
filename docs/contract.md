# 산출물 계약

`data/derived/` 의 JSON은 **백엔드와의 계약**이다. 파이프라인 내부는 자유롭게
고쳐도 되지만, 여기 적힌 필드 이름과 의미가 바뀌면 백엔드가 깨진다.

스키마를 바꿀 때는 이 문서를 먼저 고치고 백엔드 담당과 합의한 뒤 코드를 고친다.

## places.json — 장소 마스터

앱의 `.dc.html` 에 하드코딩된 장소를 추출한 것. 백엔드가 DB에 적재한다.

```json
{
  "count": 1171,
  "places": [
    {
      "id": "gj2",
      "block": "gyeongju",
      "nameKo": "쪽샘 44호 신라공주묘",
      "nameEn": "Jjoksaem Tomb No. 44",
      "region": "경주",
      "catApp": "herit",
      "catFinal": "herit",
      "catFinalKo": "역사·문화",
      "catSource": "app",
      "lat": 35.8397,
      "lng": 129.2163,
      "stayMin": 40,
      "hours": "09:00–18:00",
      "youtubeId": "4m9eLr-NofA",
      "sourceKo": "쪽샘길 60 지오코딩 확인",
      "inactive": false
    }
  ]
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | string | 앱이 쓰는 장소 ID. **기본키로 쓸 것** |
| `block` | string | 앱 DATA의 소속 블록 (`gyeongju`·`jeju`·`nation` 등) |
| `nameKo` / `nameEn` | string | 장소명 |
| `region` | string \| null | 시군 단위 지역명. 109종 |
| `catApp` | string | 앱 HTML의 **원본** 값. 손으로 넣은 값이라 신뢰도가 낮다 |
| `catFinal` | string | **백엔드는 이 값을 쓴다.** 교정이 있으면 교정본 |
| `catFinalKo` | string | `catFinal` 의 한글명. 팀원 추천 코드와 맞춘 이름 |
| `catSource` | string | `app`(원본 유지) 또는 `tourapi`(교정됨) |
| `lat` / `lng` | number | WGS84 좌표 |
| `stayMin` | int \| null | 권장 체류시간(분) |
| `hours` | string \| null | 운영시간. 자유 형식 문자열이라 파싱하지 말 것 |
| `youtubeId` | string \| null | 연결된 영상 ID. 없으면 영상 없는 장소 |
| `sourceKo` | string \| null | 좌표 근거 |
| `inactive` | bool | 앱이 목록에서 내려둔 장소. 추천 순서에서 뒤로 민다 |

### 주의

- **`catApp` 을 그대로 쓰지 말 것. `catFinal` 을 쓴다.** `catApp` 은 앱 HTML에
  손으로 넣은 값이라 지역별로 기준이 다르다(제주·부산의 해변이 `sea` 가 아니라
  `heal` 로 들어가 있었다). `catFinal` 은 TourAPI 공식 분류로 교정한 값이다
- **앱 HTML은 고치지 않는다.** 교정은 이 파이프라인 안에서만 덧씌운다. 그래서
  무엇을 왜 바꿨는지 `categories.json` 과 `reports/reclassify.md` 로 되짚을 수
  있고, 앱 레포와 충돌하지 않는다
- 교정 규모: 1,171곳 중 918곳 TourAPI 매칭 · 287곳이 변경 대상 · 그중
  **168곳만 반영**했다. 나머지 119곳은 신뢰도가 낮거나 계통 오류(숙박시설
  오매칭·먹자골목)가 있어 보류했다 — `reports/reclassify.md` 참고
- **`stayMin` 은 추정값이다.** 고유값이 21개뿐이고 99.9%가 10분 배수라,
  근거 있는 측정치가 아니다. 일정 길이 계산에 쓰되 정확도를 주장하지 말 것
- `region` 이 `null` 인 장소가 있을 수 있다. `nation` 블록에서 `locKo` 가
  빠진 경우다. 적재 전에 확인한다

## datalab.json — 지역×테마 강도 (TFI)

```json
{
 "themes": ["herit", "heal", "activity", "food"],
 "themeLabels": {"herit": "역사·문화유산", "heal": "자연·힐링",
                 "activity": "체험·활동", "food": "미식"},
 "regions": ["거제", "경주", "부산", "서울", "제주"],
 "tfi": {
  "경주": {"herit": 1.0, "heal": 0.0, "activity": 0.71, "food": 0.47}
 },
 "detail": {
  "경주": {
   "spotShare": {"herit": 46.55, "heal": 17.24},
   "spotCount": 58,
   "golfExcluded": 12,
   "consumptionShare": {"food": 32.6, "shopping": 20.2},
   "appCategoryShare": {"herit": 65.9, "activity": 18.2, "sea": 6.8},
   "age_consumption": {}, "flows": {"in": [], "out": []},
   "source_files": []
  }
 }
}
```

| 필드 | 설명 |
|---|---|
| `themes` | 테마 축 4종. **앱 카테고리와 같은 이름**을 쓴다 |
| `tfi` | 지역×테마 강도, **0~1 정규화**. 추천 가중치로 쓴다 |
| `detail[].spotShare` | 인기관광지 분류 구성비(%) — **장소 개수 기준** |
| `detail[].spotCount` | 위 비중의 분모가 된 관광지 수 |
| `detail[].golfExcluded` | 모수에서 뺀 골프장 수 (아래 주의 참고) |
| `detail[].campingShare` | 인기관광지 중 캠핑장 비율(%) (아래 주의 참고) |
| `detail[].consumptionShare` | 관광소비 업종 비중(%) — **소비액 기준** |
| `detail[].appCategoryShare` | 앱 장소의 카테고리 분포(%). 재분류 반영 |
| `detail[].flows` | 유입·유출 연관지역. 동선 그래프 간선 후보 |

### 주의

- **`tfi` 값은 받은 지역들 사이의 상대값이다.** 전국 기준이 아니다. 지역이
  1곳뿐이면 비교 기준이 없어 `null` 이 들어간다. `null` 을 0으로 치환하지
  말 것 — "약하다"가 아니라 "모른다"는 뜻이다
- 지역을 추가하면 **기존 지역의 tfi 값도 바뀐다.** 평균이 기준이기 때문이다.
  백엔드는 이 파일을 통째로 다시 읽어야 하며, 지역별 부분 갱신을 하면 안 된다
- **`themes` 에 `sea` 가 없다.** 데이터랩 인기관광지는 분류를 중분류까지만
  주기 때문에, NA02(자연경관 하천‧해양)에서 해변만 뗄 수 없다. 바다 비중이
  필요하면 `appCategoryShare` 를 쓴다 — 그쪽은 TourAPI 소분류를 받아와서
  `sea` 가 따로 있다
- **`spotShare` 와 `consumptionShare` 는 단위가 다르다.** 각각 장소 개수와
  소비액 기준이다. 한 표에 나란히 놓고 비교하지 말 것. (TFI는 테마별로 따로
  정규화하므로 이 차이의 영향을 받지 않는다)
- **캠핑장은 숙박으로 분류돼 테마 모수에 없다.** TourAPI 분류상 캠핑은
  숙박(AC05)이다. 보통은 문제가 안 되는데 **영월은 인기관광지의 37%가
  캠핑장**이라, 빼고 나면 그 지역의 가장 큰 관광 성격이 사라진다. 그렇다고
  자연(heal)으로 보내면 캠핑장이 모수의 절반을 먹어 영월이 제주보다 자연
  강세로 뒤집히고 실제 성격(단종 유배지·박물관)인 역사가 0.86→0.43으로
  내려간다. 그래서 **축은 그대로 두고 `campingShare` 로 따로 남겼다.**
  캠핑 수요를 다루려면 이 값을 별도 신호로 쓴다
- **골프장은 모수에서 뺐다.** 데이터랩 '육상레저스포츠'의 절반 이상이
  골프장인 지역이 있는데(경주 28곳 중 12곳), 앱은 골프장을 다루지 않는다.
  빼지 않으면 "경주는 체험·활동 강세"라는 잘못된 결론이 나온다. 이름으로
  거르므로 완벽하지 않다 — `golfExcluded` 수치로 영향을 확인할 수 있다

## staytime.json — 지역 체류시간

데이터랩 '전국' 다운로드의 시군구 체류시간을 앱 지역 단위로 묶은 것.

```json
{
 "latestYear": "2025",
 "source": "전국 다운로드 (2025년, 시군구 229개)",
 "nationalAverage": {"기초": {"2023": 1304.0, "2025": 1209.0}, "광역": {}},
 "lodgingRatio": {"경주시": ["2025", 16.3]},
 "regions": [
  {"region": "경주", "tier": "기초", "subUnits": 1,
   "stayMinutes": 1222.0, "lodgingDays": 2.44, "index": 1.011,
   "appPlaces": 45, "appStayMinSum": 3200, "appStayMinMean": 71.1,
   "visitsToSeeAll": 2.62}
 ]
}
```

| 필드 | 설명 |
|---|---|
| `stayMinutes` | 그 지역 **1회 방문 총 체류시간(분)**. 이동·식사·숙박 포함 |
| `lodgingDays` | 평균 숙박일수 |
| `index` | 전국 평균 대비 배수. **추천 일정 길이를 지역마다 다르게 잡는 값** |
| `subUnits` | 합친 시군구 수 (서울 25, 부산 16 등). 1이면 단일 |
| `appPlaces` / `appStayMinSum` / `appStayMinMean` | 그 지역 앱 장소의 수·시간합·평균 |
| `visitsToSeeAll` | 앱 장소를 다 보려면 몇 번 방문해야 하는가 |

### 주의

- **`stayMinutes` 와 `places.json` 의 `stayMin` 은 단위가 다르다.** 전자는
  지역 1회 방문 총량(1,000~4,300분), 후자는 장소당 관람시간(40~90분)이다.
  나누거나 빼지 말 것
- **`index` 만 쓰는 것을 권한다.** 일정 길이에 곱하면 지역 특성이 반영된다
- `visitsToSeeAll` 이 1을 크게 넘는 지역(서울 3.9 · 제주 3.8 · 부산 2.6)은
  앱이 1회 방문에 담을 수 없는 분량을 들고 있다는 뜻이다. 추천은 그보다
  적게 골라야 한다
- `nationalAverage` 는 시군구 **단순평균**이다. 데이터랩 공표값(가중평균)과
  다르며, 이유는 `reports/staytime.md` 에 적혀 있다

## categories.json — TourAPI 재분류 원장

`places.json` 의 `catFinal` 을 만든 근거다. **백엔드가 직접 읽을 필요는 없고**,
무엇을 왜 바꿨는지 되짚을 때 본다.

| 필드 | 설명 |
|---|---|
| `catApp` / `catOfficial` | 앱 원본 / TourAPI 판정 |
| `lclsSystm1/2/3` | TourAPI 대·중·소분류 코드 |
| `similarity` / `distanceKm` | 이름 유사도, 앱 좌표와의 거리 |
| `confidence` | `high` / `medium` / `low` |
| `apply` / `applyNote` | 앱에 반영했는지, 안 했다면 이유 |
| `note` | 미매칭 사유 |

사람이 읽을 요약은 `reports/reclassify.md` 에 있다.

## courses.json — 영상 IP 코스와 순서

앱의 핵심 화면("영상 속 장소를 순서대로 따라 걷기")이 쓰는 데이터. 코스별
`.dc.html` 5개에서 뽑는다 — 장소 마스터(`Tour Planner.dc.html`)에는 **순서가 없다.**

```json
{
 "count": 5,
 "courses": [
  {
   "courseId": "jeju-k-drama-route",
   "title": "제주 K-Drama",
   "regions": ["제주"],
   "count": 11,
   "stayMinSum": 970,
   "places": [
    {"seq": 1, "coursePlaceId": "jd1", "placeId": "jd1",
     "nameKo": "성산일출봉", "region": "제주",
     "catFinal": "heal", "stayMin": 110,
     "youtubeId": "ps1", "videoTitle": "폭싹 속았수다 (2025)",
     "sceneKo": "애순이네 동네"}
   ]
  }
 ]
}
```

| 필드 | 설명 |
|---|---|
| `courseId` | 코스 식별자. `/v1/courses?courseId=` 와 `/v1/places?course=` 에 쓴다 |
| `regions` | 그 코스가 지나는 지역. 여러 곳일 수 있다(RESCENE 은 7곳) |
| `stayMinSum` | 코스 전체 체류시간 합(분). 이동시간은 포함하지 않는다 |
| `places[].seq` | **코스 안에서의 순번.** 이 순서대로 걷는다 |
| `places[].placeId` | 장소 마스터(`places.json`)의 `id` |
| `places[].catFinal` | 마스터의 교정 카테고리를 그대로 쓴다 |
| `places[].videoTitle` · `sceneKo` | 영상 제목과 장면. **코스 파일에만 있다** |

### 주의

- **한 장소가 여러 코스에 나올 수 있다.** `places.json` 쪽에는 `courses` 배열로
  붙는다 (`[{courseId, title, seq}, …]`)
- 순서대로 보여 주는 화면은 `/v1/courses` 를 쓴다. `/v1/places` 는 지역·카테고리
  기준이라 코스 순서가 없다
- `stayMinSum` 은 **체류시간만** 더한 값이다. 실제 일정은 이동시간을 더해야 하고,
  그 계산은 앱(`Tour Planner.dc.html`)과 `Tour-Navigator-App/체류시간 산정/` 에 있다
