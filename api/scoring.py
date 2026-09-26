# -*- coding: utf-8 -*-
"""추천 점수 계산. recommend/src/calc2.py 의 점수식을 요청 단위로 다시 쓴 것.

calc2.py 는 사용자 유형 8개를 미리 계산해 calc2.json 에 넣어 둔다. API 는 임의의
설문 응답을 받아야 하므로 같은 식을 요청마다 돈다. **식은 그대로다** — 군집별
가중치 W 와 코스 구성 share 의 내적이고, 무거운 계산은 없다.

  점수 = fit + interest + region
         │     │          └ 지역 보정 (국민여행조사·외래관광객조사, ±0.05)
         │     └ 관심 카테고리 보너스
         └ 군집선호 × 코스구성  (calc2.json 에 군집별로 미리 계산돼 있다)
"""
CLUSTERS = [f"C{i}" for i in range(1, 11)]


def rank_themes(data, cluster, interests=(), night=False, region_adj=None):
    """테마를 점수 순으로 정렬해 돌려준다.

    data       calc2.json 을 읽은 dict
    cluster    'C1'~'C10'
    interests  관심 카테고리 인덱스 (cats 기준 0~4)
    night      야경 선호
    region_adj {테마: 보정값} — 없으면 0. 데이터랩 TFI 를 여기에 넣을 수 있다.
    """
    cats = data["cats"]
    idx = [i for i in interests if 0 <= i < len(cats)]
    out = []
    for theme, p in data["P"].items():
        fit = p["fit"].get(cluster)
        if fit is None:
            continue
        # 관심 카테고리 비중 + 야경 선호를 절반 가중으로 더한다 (calc2.py 와 동일)
        bonus = .5 * (sum(p["share"][i] for i in idx) + (p["night"] if night else 0))
        adj = (region_adj or {}).get(theme, 0.0)
        out.append({
            "theme": theme,
            "fit": round(fit, 4),
            "interest": round(bonus, 4),
            "region": round(adj, 4),
            "score": round(fit + bonus + adj, 4),
            "share": {c: round(v, 4) for c, v in zip(cats, p["share"])},
        })
    out.sort(key=lambda x: -x["score"])
    return out
