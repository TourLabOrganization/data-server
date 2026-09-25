# data-server

Tour Navigator의 데이터 파이프라인. 한국관광 데이터랩과 TourAPI를 받아
백엔드가 쓸 JSON을 만든다.

2026 한국관광 데이터랩 활용 경진대회 출품작.

## 이 레포가 하는 일

```
한국관광 데이터랩 CSV  (사람이 내려받아 data/datalab_raw/ 에 둔다)
TourAPI              (공공데이터포털)
앱의 장소 1,171곳     (Tour-Navigator-App 의 .dc.html)
        │
        ▼  pipeline/ — 가끔 손으로 돌리는 배치 작업
data/derived/*.json  ← 백엔드와의 계약. 이것만 커밋된다
        │
        ▼
backend (Spring Boot) → frontend
```

**이 레포는 상시 기동하는 서버가 아니다.** 파이프라인을 돌려 JSON을 만들고,
그 JSON을 커밋해 두면 백엔드는 파이프라인을 다시 돌리지 않고 읽기만 한다.
추천 계산을 실시간으로 서빙해야 할 때가 되면 `api/` 를 여기에 추가한다.

## 빠른 시작

의존성이 없다. Python 3.9 이상이면 그대로 돈다.

```bash
cp .env.example .env     # APP_REPO 경로만 맞추면 된다
make all
```

개별 실행:

```bash
python -m pipeline.places     # 앱 HTML → 장소 마스터
python -m pipeline.datalab    # 데이터랩 CSV → 지역×테마 강도(TFI)
python -m pipeline.verify     # 데이터랩 ↔ 앱 매칭 검증
```

## 산출물

`data/derived/` 에 들어가며, 이게 백엔드와의 계약이다. 스키마는
`docs/contract.md` 를 본다.

| 파일 | 내용 | 쓰는 곳 |
|---|---|---|
| `places.json` | 장소 1,171곳 (좌표·카테고리·체류시간) | 백엔드 DB 적재 |
| `datalab.json` | 지역×테마 강도 지수(TFI) 5개 지역 | 추천 가중치 |

## 원본 데이터

데이터랩 CSV는 **커밋하지 않는다.** 제공처 이용조건상 재배포할 수 없고,
이 레포는 공개 저장소다. `data/datalab_raw/.gitignore` 가 전부 제외한다.

즉 원본은 각자 로컬에만 있다. 받은 zip은 따로 백업해 둘 것. 어떤 탭을 받아야
하는지는 `data/datalab_raw/README.md` 에 적혀 있다.

## 지금 들어 있는 것

| | 상태 |
|---|---|
| 장소 마스터 추출 | 1,171곳 / 109개 지역 |
| 데이터랩 TFI | 경주·거제·서울·제주·부산 5개 지역 |
| 앱 ↔ 데이터랩 검증 | 매칭률 38%, 순위상관 평균 +0.43 |

## 아직 없는 것

- TourAPI 공식 분류로 장소 카테고리 재분류 (`pipeline/tourapi.py`)
- 데이터랩 체류시간 기반 일정 길이 검증 (`pipeline/staytime.py`)
- 팀원 추천 알고리즘 (`recommend/`)
- 추천 API 서빙 (`api/`)

## 문서

| 알고 싶은 것 | 문서 |
|---|---|
| 파이프라인이 무엇을 어떻게 계산하나 | `docs/pipeline.md` |
| 산출 JSON 스키마 (백엔드가 읽을 것) | `docs/contract.md` |
| 데이터랩의 어떤 탭을 왜 썼나 | `docs/datalab.md` |
| 브랜치·커밋 규칙 | `CLAUDE.md` |
