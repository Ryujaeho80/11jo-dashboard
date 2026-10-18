"""레이팅(백분위+추세) + 러닝스타일(선행성향+추입성향) 4개 지표를 합친 최종 조합을 백테스트.

지금까지 2개씩 묶은 조합은 각각 검증됐지만(레이팅조합 -0.2519, 러닝스타일조합 -0.3034),
4개를 전부 합친 조합은 아직 검증된 적이 없다 — "둘 다 좋았으니 합치면 더 좋을 것"이라는
가정을 세우지 않고, 그대로 백테스트해서 숫자로 확인한다.

전부 point-in-time(미래 데이터 미사용) 원칙 동일 적용.

사용법:
    python scripts/backtest_final_combo.py
"""
import pandas as pd

from analyze_entry_candidates import _distance_num, _parse_date, load_population
from backtest_rating_percentile import compute_percentile_asof, LOOKBACK_DAYS, MIN_HISTORY_DAYS
from backtest_running_style import compute_position_change, SECTIONAL_POINTS

FIELD_CSV = "data/raw/race_results/race_field_3.csv"
META_CSV = "data/raw/race_results/race_meta_3.csv"
OUT_CSV = "data/processed/backtest_final_combo_results.csv"


def build_dataset():
    field = pd.read_csv(FIELD_CSV, dtype=str)
    meta = pd.read_csv(META_CSV, dtype=str)
    df = field.merge(meta[["경주일자", "경주번호", "등급", "거리", "주로상태"]],
                      on=["경주일자", "경주번호"], how="left")
    df["경주일자_dt"] = df["경주일자"].apply(_parse_date)
    df["순위_num"] = pd.to_numeric(df["순위"], errors="coerce")
    df["레이팅_num"] = pd.to_numeric(df["레이팅"], errors="coerce")
    df["거리_num"] = df["거리"].apply(_distance_num)
    df = compute_position_change(df)  # 초반백분위, 막판백분위, 포지션변화

    df = df.dropna(subset=["경주일자_dt", "순위_num", "등급"]).sort_values(
        ["마호_hrNo", "경주일자_dt"])

    # 레이팅추세 (자기 자신의 직전 출전 대비)
    df["직전레이팅"] = df.groupby("마호_hrNo")["레이팅_num"].shift(1)
    df["레이팅추세"] = df["레이팅_num"] - df["직전레이팅"]

    # 과거평균 선행성향/추입성향 (자기 자신의 과거 기록만, 이 경주 제외)
    df["과거평균_초반백분위"] = df.groupby("마호_hrNo")["초반백분위"].transform(
        lambda s: s.shift(1).expanding().mean())
    df["과거평균_포지션변화"] = df.groupby("마호_hrNo")["포지션변화"].transform(
        lambda s: s.shift(1).expanding().mean())

    return df


def main():
    df = build_dataset()
    pop_for_percentile = load_population()
    pop_for_percentile["거리_num"] = pop_for_percentile["거리"].apply(_distance_num)

    min_date = df["경주일자_dt"].min()
    backtest_start = min_date + pd.Timedelta(days=MIN_HISTORY_DAYS)

    rows = []
    for rc_date_dt, day_rows in df[df["경주일자_dt"] >= backtest_start].groupby("경주일자_dt"):
        cutoff_start = rc_date_dt - pd.Timedelta(days=LOOKBACK_DAYS)
        history_pool = pop_for_percentile[
            (pop_for_percentile["경주일자_dt"] < rc_date_dt) &
            (pop_for_percentile["경주일자_dt"] >= cutoff_start)]
        if len(history_pool) < 5:
            continue

        for _, row in day_rows.iterrows():
            if pd.isna(row["레이팅_num"]):
                continue
            pct, tier, pool_n = compute_percentile_asof(row, history_pool)
            if pct is None:
                continue
            if pd.isna(row["레이팅추세"]) or pd.isna(row["과거평균_초반백분위"]) or pd.isna(row["과거평균_포지션변화"]):
                continue
            field_size = row.get("출주두수_실측")
            rows.append({
                "경주일자": row["경주일자"], "경주번호": row["경주번호"],
                "마명": row["마명"], "마호_hrNo": row["마호_hrNo"],
                "레이팅백분위": pct, "레이팅추세": row["레이팅추세"],
                "선행성향": row["과거평균_초반백분위"], "추입성향": row["과거평균_포지션변화"],
                "실제순위": row["순위_num"], "출주두수": field_size,
                "순위비율": row["순위_num"] / field_size if field_size else None,
            })

    result = pd.DataFrame(rows).dropna(subset=["순위비율"])
    result.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"4개 지표 모두 계산 가능한 출전기록: {len(result)}건")

    if len(result) < 30:
        print("표본 부족")
        return

    for col in ["레이팅백분위", "레이팅추세", "선행성향", "추입성향"]:
        result[f"r_{col}"] = result[col].rank(pct=True)

    combos = {
        "레이팅조합(백분위+추세)": ["r_레이팅백분위", "r_레이팅추세"],
        "러닝스타일조합(선행+추입)": ["r_선행성향", "r_추입성향"],
        "4지표 전체조합": ["r_레이팅백분위", "r_레이팅추세", "r_선행성향", "r_추입성향"],
    }
    print("\n=== 같은 표본(동일 4,xxx건 교집합)에서 조합별 비교 ===")
    for name, cols in combos.items():
        score = result[cols].mean(axis=1)
        corr = pd.concat([score.rename("점수"), result["순위비율"]], axis=1).corr(
            method="spearman").iloc[0, 1]
        bucket = pd.qcut(score, 5, duplicates="drop")
        stats = result.groupby(bucket, observed=True).agg(
            표본수=("순위비율", "count"), 평균순위비율=("순위비율", "mean"),
            승률=("실제순위", lambda s: (s == 1).mean()),
            복승률=("실제순위", lambda s: (s <= 3).mean()),
        ).round(4)
        print(f"\n[{name}] Spearman={corr:.4f}")
        print(stats.to_string())


if __name__ == "__main__":
    main()
