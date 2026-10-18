""""하위등급에서 잘 뛰고 올라오면"(승급) 직후 성적이 실제로 떨어지는지 검증.

등급 서열은 라벨(국1/국OPEN/혼3 등)만으로는 직관과 안 맞을 수 있어(예: 국OPEN 평균
레이팅 49.0 < 국3등급 55.5) 추측하지 않고, **실측 평균 레이팅으로 서열을 산출**한다.
그 서열 기준으로 "직전 경주보다 등급이 올라간 경우"를 승급으로 정의하고, 승급 직후
레이스의 성적이 승급 없이 같은 등급을 유지한 레이스보다 체계적으로 나쁜지 확인한다.

point-in-time 원칙: 등급 서열도 전체 데이터가 아니라 '그 시점까지의 데이터'로 산출해야
미래 정보 누수가 없다 — 간단화를 위해 여기서는 등급 서열 자체는 전체 12개월로 고정하되
(서열은 거의 안 바뀌는 구조적 성격이라 큰 문제가 아님을 인지하고), 성적 비교는 point-in-time
레이팅 백분위 로직과 별개로 '승급 여부'라는 범주형 변수 하나만 검증한다.

사용법:
    python scripts/backtest_class_promotion.py
"""
import pandas as pd

from analyze_entry_candidates import _parse_date

FIELD_CSV = "data/raw/race_results/race_field_3.csv"
META_CSV = "data/raw/race_results/race_meta_3.csv"
OUT_CSV = "data/processed/backtest_class_promotion_results.csv"


def main():
    field = pd.read_csv(FIELD_CSV, dtype=str)
    meta = pd.read_csv(META_CSV, dtype=str)
    df = field.merge(meta[["경주일자", "경주번호", "등급"]], on=["경주일자", "경주번호"], how="left")
    df["레이팅_num"] = pd.to_numeric(df["레이팅"], errors="coerce")
    df["순위_num"] = pd.to_numeric(df["순위"], errors="coerce")
    df["경주일자_dt"] = df["경주일자"].apply(_parse_date)
    field_size = df.groupby(["경주일자", "경주번호"])["순위"].transform("count")
    df["출주두수_실측"] = field_size
    df["순위비율"] = df["순위_num"] / df["출주두수_실측"]

    # 등급 서열 — 실측 평균 레이팅 기준 (라벨 텍스트로 추측하지 않음)
    # 국6등급처럼 레이팅이 전혀 없는(평균=NaN) 등급은 데뷔 전 최하위 등급이 확실하므로
    # sort_values()가 NaN을 맨 뒤(=최고서열)로 보내는 기본 동작을 쓰면 안 됨 — 명시적으로 최하위 처리.
    grade_rating = df.groupby("등급")["레이팅_num"].mean()
    rated = grade_rating.dropna().sort_values()
    unrated = grade_rating[grade_rating.isna()]
    ordered_grades = list(unrated.index) + list(rated.index)  # 레이팅 없는 등급(국6 등) 최하위로 고정
    rank_map = {g: i for i, g in enumerate(ordered_grades)}
    grade_rank = grade_rating.reindex(ordered_grades)
    print("등급 서열(평균 레이팅 기준, 낮음->높음):")
    for g, r in grade_rank.items():
        print(f"  {r:6.1f}  {g}  (rank={rank_map[g]})")

    df["등급순위"] = df["등급"].map(rank_map)
    df = df.dropna(subset=["경주일자_dt", "등급순위", "순위비율"]).sort_values(["마호_hrNo", "경주일자_dt"])

    df["직전등급순위"] = df.groupby("마호_hrNo")["등급순위"].shift(1)
    df["등급변화"] = df["등급순위"] - df["직전등급순위"]
    target = df.dropna(subset=["등급변화"]).copy()  # 최소 2번째 출전부터

    target["구분"] = "유지/강등"
    target.loc[target["등급변화"] > 0, "구분"] = "승급"
    target.loc[target["등급변화"] == 0, "구분"] = "동일등급유지"
    target.loc[target["등급변화"] < 0, "구분"] = "강등"

    target.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print(f"\n분석 대상: {len(target)}건 (연속 2경주 이상 뛴 말의 2번째 이후 출전)")
    stats = target.groupby("구분").agg(
        표본수=("순위비율", "count"),
        평균순위비율=("순위비율", "mean"),
        승률=("순위_num", lambda s: (s == 1).mean()),
        복승률=("순위_num", lambda s: (s <= 3).mean()),
    ).round(4)
    print("\n=== 승급/동일/강등 직후 성적 ===")
    print(stats.to_string())

    # 승급 폭(몇 단계 올라갔는지)에 따른 효과도 확인
    promo = target[target["구분"] == "승급"].copy()
    promo["승급폭"] = pd.cut(promo["등급변화"], [0, 1, 2, 3, 100], labels=["1단계", "2단계", "3단계", "4단계+"])
    promo_stats = promo.groupby("승급폭", observed=True).agg(
        표본수=("순위비율", "count"), 평균순위비율=("순위비율", "mean"),
        승률=("순위_num", lambda s: (s == 1).mean()),
    ).round(4)
    print("\n=== 승급폭별 ===")
    print(promo_stats.to_string())


if __name__ == "__main__":
    main()
