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
all: places datalab staytime verify

places:   ## 앱 HTML → 장소 마스터
	$(PY) -m pipeline.places

datalab:  ## 데이터랩 CSV → 지역×테마 강도(TFI)
	$(PY) -m pipeline.datalab

staytime: ## 데이터랩 체류시간으로 일정 길이 검증
	$(PY) -m pipeline.staytime

verify:   ## 데이터랩 ↔ 앱 매칭 검증
	$(PY) -m pipeline.verify

tourapi:  ## TourAPI 공식 분류로 장소 재분류 (TOURAPI_KEY 필요)
	$(PY) -m pipeline.tourapi

clean:    ## 산출물과 캐시를 지운다 (원본은 건드리지 않는다)
	rm -rf data/derived/*.json data/cache/* __pycache__ pipeline/__pycache__
