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

이 레포는 두 부분이다.

- **`pipeline/`** — 가끔 손으로 돌리는 배치. CSV·TourAPI 를 읽어 JSON 을 만든다
- **`api/`** — 그 JSON 을 백엔드에 넘기는 FastAPI 서버. 무거운 계산은 하지 않는다

무거운 것(ETL·재분류·군집 학습)은 전부 배치로 끝나 있고, API 에서 도는 것은
요청마다 바뀌는 점수 정렬뿐이다.

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
python -m pipeline.staytime   # 체류시간으로 일정 길이 검증
python -m pipeline.verify     # 데이터랩 ↔ 앱 매칭 검증
python -m pipeline.tourapi    # TourAPI 공식 분류로 재분류 (키 필요, make all 에는 없음)
```

## 산출물

`data/derived/` 에 들어가며, 이게 백엔드와의 계약이다. 스키마는
`docs/contract.md` 를 본다.

| 파일 | 내용 | 쓰는 곳 |
|---|---|---|
| `places.json` | 장소 1,171곳 (좌표·카테고리·체류시간) | 백엔드 DB 적재 |
| `datalab.json` | 지역×테마 강도 지수(TFI) 5개 지역 | 추천 가중치 |
| `categories.json` | TourAPI 공식 분류 재분류 결과 | 카테고리 교정 |
| `staytime.json` | 지역별 체류시간·전국 대비 지수 | 일정 길이 조절 |
| `recommend/data/derived/calc2.json` | 사용자 유형×테마 추천 순위 | 추천 API |

검증 리포트는 `reports/` 에 마크다운으로 쌓인다.

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
| 체류시간 검증 | 38개 지역 (기초 30 · 광역 8) |
| TourAPI 재분류 | 757/1,171곳 — 일일 호출 한도로 중단, 이어받기 가능 |

## 아직 없는 것

- TourAPI 재분류 잔여 414곳 (호출 한도 해제 후 이어서 실행)
- 재분류 결과를 반영한 TFI 재계산

## 문서

| 알고 싶은 것 | 문서 |
|---|---|
| 파이프라인이 무엇을 어떻게 계산하나 | `docs/pipeline.md` |
| 산출 JSON 스키마 (백엔드가 읽을 것) | `docs/contract.md` |
| 데이터랩의 어떤 탭을 왜 썼나 | `docs/datalab.md` |
| 배포·EC2 구성 | `docs/deploy.md` |
| 브랜치·커밋 규칙 | `CLAUDE.md` |
