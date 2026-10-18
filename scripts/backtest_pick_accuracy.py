"""'같은 경주에 출전한 말들 중 이 점수로 1등을 뽑았으면 실제로 맞았는가' 검증.

backtest_final_combo.py가 확인한 건 '점수가 결과와 상관있다'(Spearman)는 것이었지,
'그 경주의 실제 경쟁자들 사이에서 점수 1위가 실제로도 잘했는가'는 다른 질문이다.
이게 실제 의사결정("이 말을 우선할 것인가")에 더 가까운 검증이므로 별도로 확인한다.

방법: backtest_final_combo.py가 만든 point-in-time 점수(backtest_final_combo_results.csv)를
그대로 재사용 — 같은 경주(경주일자+경주번호)에 출전한, 점수 계산이 가능했던 말들끼리 묶어서
점수 1위가 실제 순위에서 어땠는지 집계. 무작위로 찍었을 때의 기대 승률(1/출주두수)과 비교.

사용법:
    python scripts/backtest_pick_accuracy.py
"""
import pandas as pd

IN_CSV = "data/processed/backtest_final_combo_results.csv"
OUT_CSV = "data/processed/backtest_pick_accuracy_results.csv"


def main():
    df = pd.read_csv(IN_CSV)

    for col in ["레이팅백분위", "레이팅추세", "선행성향", "추입성향"]:
        df[f"r_{col}"] = df[col].rank(pct=True)
    df["조합점수"] = df[["r_레이팅백분위", "r_레이팅추세", "r_선행성향", "r_추입성향"]].mean(axis=1)

    # 같은 경주(경주일자+경주번호) 안에서 점수 계산 가능한 말이 2두 이상인 경우만 '비교'가 성립
    race_key = ["경주일자", "경주번호"]
    race_counts = df.groupby(race_key)["마호_hrNo"].transform("count")
    comparable = df[race_counts >= 2].copy()

    print(f"비교 가능한 경주(출전 2두 이상 점수 산출): {comparable[race_key].drop_duplicates().shape[0]}개")
    print(f"해당 경주의 출전기록: {len(comparable)}건")

    # 각 경주에서 조합점수 1위 행 추출
    top_picks = comparable.loc[comparable.groupby(race_key)["조합점수"].idxmax()].copy()
    top_picks["출주두수_비교대상"] = comparable.groupby(race_key)["마호_hrNo"].transform("count").loc[top_picks.index]
    top_picks["무작위기대승률"] = 1 / top_picks["출주두수_비교대상"]

    actual_win_rate = (top_picks["실제순위"] == 1).mean()
    actual_top3_rate = (top_picks["실제순위"] <= 3).mean()
    baseline_win_rate = top_picks["무작위기대승률"].mean()
    avg_finish_ratio_pick = (top_picks["실제순위"] / top_picks["출주두수"]).mean()

    # 비교 모집단 전체(점수 무관 무작위)의 평균 순위비율 — 베이스라인
    comparable_all_ratio = (comparable["실제순위"] / comparable["출주두수"]).mean()

    print(f"\n=== 경주 {len(top_picks)}건에서 '조합점수 1위' 픽의 실제 성적 ===")
    print(f"점수1위의 실제 승률: {actual_win_rate:.4f}  (무작위 기대 승률: {baseline_win_rate:.4f})")
    print(f"점수1위의 실제 3위이내율: {actual_top3_rate:.4f}")
    print(f"점수1위의 평균 순위비율: {avg_finish_ratio_pick:.4f}  (비교모집단 전체 평균 순위비율: {comparable_all_ratio:.4f})")
    print(f"승률 배수(무작위 대비): {actual_win_rate/baseline_win_rate:.2f}배")

    # 출주두수 구간별로도 쪼개서 확인 (두수가 많을수록 무작위 기대승률이 낮아지므로 공정 비교)
    top_picks["출주두수_구간"] = pd.cut(top_picks["출주두수_비교대상"], [1, 5, 8, 11, 20])
    bucket = top_picks.groupby("출주두수_구간", observed=True).agg(
        경주수=("실제순위", "count"),
        실제승률=("실제순위", lambda s: (s == 1).mean()),
        무작위기대승률=("무작위기대승률", "mean"),
    ).round(4)
    bucket["배수"] = (bucket["실제승률"] / bucket["무작위기대승률"]).round(2)
    print("\n출주두수 구간별:")
    print(bucket.to_string())

    top_picks.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n-> {OUT_CSV}")


if __name__ == "__main__":
    main()
