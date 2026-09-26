# 파이프라인 진입점. `make all` 하나로 전체가 돈다.
#
# .env 가 있으면 읽어서 APP_REPO·TOURAPI_KEY 를 넘긴다.
ifneq (,$(wildcard .env))
include .env
export
endif

PY ?= python3

.PHONY: all places datalab staytime verify tourapi clean

# tourapi 는 API 키와 호출 한도가 필요해서 all 에 넣지 않는다. 따로 돌린다.
all: places courses datalab staytime verify

places:   ## 앱 HTML → 장소 마스터
	$(PY) -m pipeline.places

courses:  ## 코스 .dc.html → 순서가 있는 장소 목록
	$(PY) -m pipeline.courses

datalab:  ## 데이터랩 CSV → 지역×테마 강도(TFI)
	$(PY) -m pipeline.datalab

staytime: ## 데이터랩 체류시간으로 일정 길이 검증
	$(PY) -m pipeline.staytime

verify:   ## 데이터랩 ↔ 앱 매칭 검증
	$(PY) -m pipeline.verify

tourapi:  ## TourAPI 공식 분류로 장소 재분류 (TOURAPI_KEY 필요)
	$(PY) -m pipeline.tourapi

clean:    ## 다시 만들 수 있는 산출물만 지운다
	# categories.json 과 data/cache/ 는 지우지 않는다. TourAPI 호출 1,500여 회가
	# 들어간 결과라 일일 한도 때문에 당일 재생성이 안 될 수 있다.
	rm -f data/derived/places.json data/derived/datalab.json \
	      data/derived/staytime.json
	rm -rf __pycache__ pipeline/__pycache__

clean-cache: ## TourAPI 캐시까지 지운다 (재조회에 호출 한도가 든다)
	rm -rf data/cache/*

serve:    ## API 서버를 로컬에서 띄운다 (개발용)
	$(PY) -m uvicorn api.main:app --reload --port 8000
