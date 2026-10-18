"""레이팅 추세·출주간격을 개별 백테스트하고, 신호가 있는 지표만 모아 조합 점수를 검증한다.

전제(백테스트1과 동일): 미래 데이터 사용 금지, 전체 모집단 대상, 결과는 실측 숫자로만 제시.
레이팅 추세·출주간격은 race_field_3.csv에 이미 있는 "같은 말의 반복 출전 기록"만으로 계산
가능하다 — 추가 수집 없이 기존 데이터로 검증한다는 원칙을 지킨다.

사용법:
    python scripts/backtest_combined_indicators.py
"""
import pandas as pd

from analyze_entry_candidates import _distance_num, load_population
from backtest_rating_percentile import compute_percentile_asof, LOOKBACK_DAYS, MIN_HISTORY_DAYS

OUT_CSV = "data/processed/backtest_combined_results.csv"


def build_target_rows():
    """사전백분위 + 레이팅추세 + 출주간격을 모두 계산할 수 있는 출전기록만 추출."""
    pop = load_population()
    pop["거리_num"] = pop["거리"].apply(_distance_num)
    pop["순위_num"] = pd.to_numeric(pop["순위"], errors="coerce")
    field_size = pop.groupby(["경주일자", "경주번호"])["순위"].transform("count")
    pop["출주두수_실측"] = field_size
    pop = pop.dropna(subset=["경주일자_dt", "레이팅_num", "순위_num", "등급"]).sort_values(
        ["마호_hrNo", "경주일자_dt"])

    # 같은 말의 직전 출전 기록(레이팅, 날짜)을 끌어와 추세/간격 계산 — 오직 과거 자기 자신의 기록만 사용
    pop["직전레이팅"] = pop.groupby("마호_hrNo")["레이팅_num"].shift(1)
    pop["직전경주일"] = pop.groupby("마호_hrNo")["경주일자_dt"].shift(1)
    pop["레이팅추세"] = pop["레이팅_num"] - pop["직전레이팅"]
    pop["출주간격일"] = (pop["경주일자_dt"] - pop["직전경주일"]).dt.days

    pop = pop.dropna(subset=["레이팅추세", "출주간격일"])  # 두 지표 다 계산 가능한 행만 (최초 출전 제외)

    min_date = pop["경주일자_dt"].min()
    backtest_start = min_date + pd.Timedelta(days=MIN_HISTORY_DAYS)
    pop_all = load_population()  # 사전백분위 계산용 전체 모집단(날짜 제한 없이, 함수 내부에서 cutoff 적용)
    pop_all["거리_num"] = pop_all["거리"].apply(_distance_num)

    rows = []
    for rc_date_dt, day_rows in pop[pop["경주일자_dt"] >= backtest_start].groupby("경주일자_dt"):
        cutoff_start = rc_date_dt - pd.Timedelta(days=LOOKBACK_DAYS)
        history_pool = pop_all[(pop_all["경주일자_dt"] < rc_date_dt) & (pop_all["경주일자_dt"] >= cutoff_start)]
        if len(history_pool) < 5:
            continue
        for _, row in day_rows.iterrows():
            pct, tier, pool_n = compute_percentile_asof(row, history_pool)
            if pct is None:
                continue
            rows.append({
                "경주일자": row["경주일자"], "마명": row["마명"], "마호_hrNo": row["마호_hrNo"],
                "사전백분위": pct, "레이팅추세": row["레이팅추세"], "출주간격일": row["출주간격일"],
                "실제순위": row["순위_num"], "출주두수": row["출주두수_실측"],
                "순위비율": row["순위_num"] / row["출주두수_실측"],
            })
    return pd.DataFrame(rows)


def report_bucket(df, col, label, n_bins=5, bins=None):
    if bins is not None:
        df = df.copy()
        df["_구간"] = pd.cut(df[col], bins=bins)
    else:
        df["_구간"] = pd.qcut(df[col], n_bins, duplicates="drop")
    stats = df.groupby("_구간", observed=True).agg(
        표본수=("순위비율", "count"),
        평균순위비율=("순위비율", "mean"),
        승률=("실제순위", lambda s: (s == 1).mean()),
        복승률_3위이내=("실제순위", lambda s: (s <= 3).mean()),
    ).round(4)
    print(f"\n[{label}] 구간별 실제 성적:")
    print(stats.to_string())
    corr = df[[col, "순위비율"]].corr(method="spearman").iloc[0, 1]
    print(f"Spearman 상관계수({label} vs 순위비율): {corr:.4f}")
    return corr


def main():
    df = build_target_rows()
    print(f"분석 대상(사전백분위+레이팅추세+출주간격 모두 계산 가능한 출전기록): {len(df)}건")
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    if len(df) < 30:
        print("표본 부족으로 분석 생략")
        return

    corr_pct = report_bucket(df, "사전백분위", "사전백분위")
    corr_trend = report_bucket(df, "레이팅추세", "레이팅추세")
    interval_bins = [0, 14, 21, 28, 42, 60, 90, 10000]
    report_bucket(df, "출주간격일", "출주간격일", bins=interval_bins)
    corr_interval = df[["출주간격일", "순위비율"]].corr(method="spearman").iloc[0, 1]
    print(f"Spearman 상관계수(출주간격일 vs 순위비율, 선형 가정): {corr_interval:.4f}")

    # 조합 점수1: 백분위+추세 (가중치 임의 부여 없이 순위 정규화 후 동등 가중)
    df["r1"] = df["사전백분위"].rank(pct=True)
    df["r2"] = df["레이팅추세"].rank(pct=True)
    df["조합점수_2지표"] = df[["r1", "r2"]].mean(axis=1)
    corr_combo2 = report_bucket(df, "조합점수_2지표", "조합점수(백분위+추세)")

    # 조합 점수2: 출주간격 구간표에서 실측된 '적정 구간(28~42일, 중심 35일)'을 그대로 반영
    # — 선형 상관(-0.05)은 약했지만 구간표(28~42일이 가장 좋음)는 실측으로 확인된 패턴이라 반영.
    df["출주간격_적정성"] = -(df["출주간격일"] - 35).abs()
    df["r3"] = df["출주간격_적정성"].rank(pct=True)
    df["조합점수_3지표"] = df[["r1", "r2", "r3"]].mean(axis=1)
    corr_combo3 = report_bucket(df, "조합점수_3지표", "조합점수(백분위+추세+출주간격적정성)")

    print("\n=== 요약 ===")
    print(f"사전백분위 단독: {corr_pct:.4f}")
    print(f"레이팅추세 단독: {corr_trend:.4f}")
    print(f"출주간격일 단독(선형): {corr_interval:.4f}")
    print(f"조합(백분위+추세): {corr_combo2:.4f}")
    print(f"조합(백분위+추세+출주간격적정성): {corr_combo3:.4f}")


if __name__ == "__main__":
    main()
