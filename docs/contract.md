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
      "lat": 35.8397,
      "lng": 129.2163,
      "stayMin": 40,
      "hours": "09:00–18:00",
      "youtubeId": "4m9eLr-NofA",
      "sourceKo": "쪽샘길 60 지오코딩 확인"
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
| `catApp` | string | 앱 카테고리. `heal` `herit` `activity` `food` `sea` `stay` |
| `lat` / `lng` | number | WGS84 좌표 |
| `stayMin` | int \| null | 권장 체류시간(분) |
| `hours` | string \| null | 운영시간. 자유 형식 문자열이라 파싱하지 말 것 |
| `youtubeId` | string \| null | 연결된 영상 ID. 없으면 영상 없는 장소 |
| `sourceKo` | string \| null | 좌표 근거 |

### 주의

- **`catApp` 은 지금 신뢰할 수 없다.** 손으로 넣은 값이라 지역별로 기준이
  다르다. 예를 들어 제주·부산의 해변이 `sea` 가 아니라 `heal` 로 들어가 있다.
  교정된 값은 `categories.json` 의 `catOfficial` 에 있다 (재분류 완료,
  1,171곳 중 918곳 매칭 · 287곳 변경 대상). 어느 쪽을 앱에 반영할지는
  `reports/reclassify.md` 의 신뢰도를 보고 정한다
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
- **골프장은 모수에서 뺐다.** 데이터랩 '육상레저스포츠'의 절반 이상이
  골프장인 지역이 있는데(경주 28곳 중 12곳), 앱은 골프장을 다루지 않는다.
  빼지 않으면 "경주는 체험·활동 강세"라는 잘못된 결론이 나온다. 이름으로
  거르므로 완벽하지 않다 — `golfExcluded` 수치로 영향을 확인할 수 있다
