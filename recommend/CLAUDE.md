# CLAUDE.md — 테마 추천 알고리즘

Claude Code가 이 폴더에서 작업할 때 따를 규칙입니다.

## 이 폴더는
Tour Navigator 앱의 테마 추천(선호 문항 → 군집 → 추천 테마 → 코스) 설계 문서, 근거 데이터, 계산 코드. 자세한 구조는 README.md.

**2026-09-26 에 `Tour-Navigator-App/테마 추천 알고리즘/` 에서 이곳(`data-server/recommend/`)
으로 옮겨왔다.** 추천 계산은 앱이 아니라 데이터 파이프라인이고, 백엔드가 그 산출물
(`data/derived/calc2.json`)을 읽기 때문이다. 코드는 그대로이고 경로 기본값만 바꿨다
(`src/classify.py` 의 `A`).

## 작업 규칙
- 계산을 바꾸면 `python run_all.py`로 `data/derived/`를 다시 만들고, 결과 JSON도 함께 커밋.
- `data/raw/`의 원자료(.SAV, .xlsx)는 절대 커밋하지 않음 (.gitignore 처리됨). `git status`에 보이면 멈추고 사용자에게 알림.
- `docs/`의 .docx·`data/`의 .xlsx는 사람이 검토하는 산출물. 코드 결과와 숫자가 달라지면 README "남은 일"에 적어 둠.
- 가중치 `W`(src/calc2.py): C1~C6은 가설값, C7~C10은 외래관광객조사 원자료로 산출. 가설값을 바꿀 때는 근거를 커밋 메시지에 적음.

## GitHub에 올리기 (TourLabOrganization/data-server)

레포 규칙은 상위 폴더의 `CLAUDE.md` 를 따른다 — 작업은 `<타입>/<기능요약>` 브랜치에서
하고 PR로 머지하며, `git push` 전에 사람에게 확인받는다.

```bash
python run_all.py     # data/derived/ 재생성
git status            # data/raw/ 원자료가 없는지 확인
```
