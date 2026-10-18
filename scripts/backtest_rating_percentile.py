"""'등급+거리+주로상태 매칭 레이팅 백분위'가 실제 경주 결과와 상관관계가 있는지 검증.

원칙 — 추측 금지, 데이터만:
1. 미래 데이터 사용 금지(lookahead bias 금지). 각 경주 시점(D)에서 그 말의 백분위를 계산할 때는
   D 이전에 실제로 존재했던 경주 결과만 모집단으로 쓴다 — analyze_entry_candidates.py가 '오늘'
   기준으로 하는 것과 동일한 계산을, 과거의 각 시점에서 재현한다.
2. 11조 28두가 아니라 부산경남 전체 7,814개 출전기록을 대상으로 한다 — 표본이 커야 통계적으로
   의미 있고, 특정 말들만 골라서 보면 결과를 입맛대로 해석할 위험이 있다.
3. 결론은 실제 계산된 숫자(상관계수, 구간별 평균 순위·승률)로만 제시한다 — 해석/추정 문구 없이
   수치 자체를 결과로 낸다.

사용법:
    python scripts/backtest_rating_percentile.py
"""
import re
from datetime import timedelta

import pandas as pd

from analyze_entry_candidates import _parse_date, _distance_num, load_population

OUT_CSV = "data/processed/backtest_rating_percentile_results.csv"
LOOKBACK_DAYS = 180  # analyze_entry_candidates.py의 lookback_months=6과 동일
MIN_HISTORY_DAYS = 90  # 최소 이만큼의 과거 데이터가 쌓인 시점부터 백테스트 대상으로 삼음


def compute_percentile_asof(target_row, history_pool: pd.DataFrame, distance_tolerance=200):
    """target_row 시점 '이전' 데이터(history_pool)만으로 백분위 계산.
    analyze_entry_candidates.class_percentile과 동일한 단계적 완화 로직."""
    grade = target_row["등급"]
    distance = target_row["거리_num"]
    track = target_row["주로상태"]
    rating = target_row["레이팅_num"]

    if pd.isna(rating) or pd.isna(grade):
        return None, None, 0

    base = history_pool[history_pool["등급"] == grade]

    match_level, pool_ratings = None, pd.Series(dtype=float)

    if pd.notna(distance) and pd.notna(track):
        tier = base[(base["거리_num"] == distance) & (base["주로상태"] == track)]
        pool_ratings = tier["레이팅_num"].dropna()
        if len(pool_ratings) >= 5:
            match_level = "등급+거리+주로 동일"

    if match_level is None and pd.notna(distance):
        tier = base[base["거리_num"] == distance]
        pool_ratings = tier["레이팅_num"].dropna()
        if len(pool_ratings) >= 5:
            match_level = "등급+거리 동일"

    if match_level is None and pd.notna(distance):
        tier = base[(base["거리_num"] - distance).abs() <= distance_tolerance]
        pool_ratings = tier["레이팅_num"].dropna()
        if len(pool_ratings) >= 5:
            match_level = f"등급+거리±{distance_tolerance}m"

    if match_level is None:
        pool_ratings = base["레이팅_num"].dropna()
        if len(pool_ratings) >= 5:
            match_level = "등급만"

    if match_level is None or len(pool_ratings) < 5:
        return None, match_level, len(pool_ratings)

    percentile = (pool_ratings < rating).mean() * 100
    return percentile, match_level, len(pool_ratings)


def main():
    pop = load_population()
    pop["거리_num"] = pop["거리"].apply(_distance_num)
    pop["순위_num"] = pd.to_numeric(pop["순위"], errors="coerce")

    # 출주두수 = 해당 경주(경주일자+경주번호)의 실제 행 수(공식 집계이지 추정 아님)
    field_size = pop.groupby(["경주일자", "경주번호"])["순위"].transform("count")
    pop["출주두수_실측"] = field_size

    pop = pop.dropna(subset=["경주일자_dt", "레이팅_num", "순위_num", "등급"]).sort_values("경주일자_dt")

    min_date = pop["경주일자_dt"].min()
    backtest_start = min_date + pd.Timedelta(days=MIN_HISTORY_DAYS)

    results = []
    # 날짜별로 그룹 처리 — 같은 날짜의 경주들은 동일한 '이전 데이터' 컷오프를 공유
    for rc_date_dt, day_rows in pop.groupby("경주일자_dt"):
        if rc_date_dt < backtest_start:
            continue
        cutoff_start = rc_date_dt - pd.Timedelta(days=LOOKBACK_DAYS)
        history_pool = pop[(pop["경주일자_dt"] < rc_date_dt) & (pop["경주일자_dt"] >= cutoff_start)]
        if len(history_pool) < 5:
            continue

        for _, row in day_rows.iterrows():
            pct, tier, pool_n = compute_percentile_asof(row, history_pool)
            if pct is None:
                continue
            results.append({
                "경주일자": row["경주일자"], "경주번호": row["경주번호"],
                "마명": row["마명"], "마호_hrNo": row["마호_hrNo"],
                "등급": row["등급"], "거리": row["거리_num"], "주로상태": row["주로상태"],
                "레이팅": row["레이팅_num"], "매칭단계": tier, "모집단수": pool_n,
                "사전백분위": round(pct, 1),
                "실제순위": row["순위_num"], "출주두수": row["출주두수_실측"],
                "순위비율": row["순위_num"] / row["출주두수_실측"],  # 1/N=1위, 1.0=꼴찌
            })

    result = pd.DataFrame(results)
    result.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"백테스트 대상 출전기록: {len(result)}건 (기간: {backtest_start.date()} ~ {pop['경주일자_dt'].max().date()})")
    print(f"-> {OUT_CSV}")

    if len(result) < 30:
        print("표본이 너무 적어 통계 분석 생략")
        return

    # 1) 상관관계 — 사전백분위가 높을수록 순위비율(낮을수록 좋은 성적)이 낮아야 함
    corr = result[["사전백분위", "순위비율"]].corr(method="spearman").iloc[0, 1]
    print(f"\nSpearman 상관계수 (사전백분위 vs 순위비율): {corr:.4f}  (음수면 '백분위 높을수록 순위 좋음'과 일치)")

    # 2) 구간별 실측 — 5분위로 나눠서 각 구간의 실제 평균 순위비율/승률/복승률
    result["백분위구간"] = pd.qcut(result["사전백분위"], 5, duplicates="drop")
    bucket_stats = result.groupby("백분위구간", observed=True).agg(
        표본수=("순위비율", "count"),
        평균순위비율=("순위비율", "mean"),
        승률=("실제순위", lambda s: (s == 1).mean()),
        복승률_3위이내=("실제순위", lambda s: (s <= 3).mean()),
    ).round(4)
    print("\n사전백분위 구간별 실제 성적:")
    print(bucket_stats.to_string())
    bucket_stats.to_csv("data/processed/backtest_bucket_stats.csv", encoding="utf-8-sig")


if __name__ == "__main__":
    main()
