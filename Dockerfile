# 파이프라인 산출물(JSON)을 이미지에 함께 굽는다. DB도 볼륨도 필요 없고,
# 배포가 곧 데이터 교체가 된다. 데이터랩은 월 단위 갱신이라 이 주기로 충분하다.
FROM python:3.12-slim

WORKDIR /app

COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY api/ ./api/
COPY data/derived/ ./data/derived/
COPY recommend/data/derived/ ./recommend/data/derived/

EXPOSE 8000
USER nobody

ENV TZ=Asia/Seoul
# 워커 1개면 충분하다. 요청당 계산이 5차원 내적이고 데이터는 메모리에 올라가 있다.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
