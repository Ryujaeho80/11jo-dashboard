"""선행/추입 성향이 실제 성적을 예측하는지 검증 — 추측 없이 데이터로만.

중요한 설계 원칙: "이 경주 안에서의 포지션변화가 이 경주 결과와 상관있다"는 질문은
거의 동어반복이다(막판 순위가 1등이면 당연히 성적도 좋음). 그래서 의미있는 질문은
"이 말이 '과거' 경주들에서 보여온 평균적인 포지션변화 성향이, '다음' 경주의 결과를
예측하는가"이다 — 레이팅추세 백테스트와 동일한 point-in-time 원칙을 그대로 적용한다.

지표 정의 (전부 실측 구간기록에서 계산, 가정 없음):
- 초반백분위 = (출주두수 - S1F순위 + 1) / 출주두수  (1.0=선두, 0에 가까울수록 후방)
- 막판백분위 = (출주두수 - G1F순위 + 1) / 출주두수
- 포지션변화 = 막판백분위 - 초반백분위  (양수=추입/뒤에서 따라붙음, 음수=초반에 비해 처짐)
  (S1F/G1F가 해당 거리에서 기록 안 된 경우 사용 가능한 가장 이른/늦은 체크포인트로 대체)

사용법:
    python scripts/backtest_running_style.py
"""
import pandas as pd

from analyze_entry_candidates import _distance_num, load_population
from backtest_rating_percentile import LOOKBACK_DAYS, MIN_HISTORY_DAYS

FIELD_CSV = "data/raw/race_results/race_field_3.csv"
META_CSV = "data/raw/race_results/race_meta_3.csv"
OUT_CSV = "data/processed/backtest_running_style_results.csv"

SECTIONAL_POINTS = ["S1F", "G8F", "G6F", "G4F", "G3F", "G2F", "G1F"]


def compute_position_change(df: pd.DataFrame) -> pd.DataFrame:
    """각 출전기록의 초반/막판 백분위·포지션변화를 실측 구간기록에서 계산."""
    df = df.copy()
    field_size = df.groupby(["경주일자", "경주번호"])["순위"].transform("count")
    df["출주두수_실측"] = field_size

    sec = df[SECTIONAL_POINTS].apply(pd.to_numeric, errors="coerce")

    def first_valid(row):
        for c in SECTIONAL_POINTS:
            if pd.notna(row[c]):
                return row[c]
        return None

    def last_valid(row):
        for c in reversed(SECTIONAL_POINTS):
            if pd.notna(row[c]):
                return row[c]
        return None

    df["초반순위"] = sec.apply(first_valid, axis=1)
    df["막판순위"] = sec.apply(last_valid, axis=1)
    df["초반백분위"] = (df["출주두수_실측"] - df["초반순위"] + 1) / df["출주두수_실측"]
    df["막판백분위"] = (df["출주두수_실측"] - df["막판순위"] + 1) / df["출주두수_실측"]
    df["포지션변화"] = df["막판백분위"] - df["초반백분위"]
    return df


def main():
    field = pd.read_csv(FIELD_CSV, dtype=str)
    meta = pd.read_csv(META_CSV, dtype=str)
    df = field.merge(meta[["경주일자", "경주번호", "등급", "거리", "주로상태"]],
                      on=["경주일자", "경주번호"], how="left")

    from analyze_entry_candidates import _parse_date
    df["경주일자_dt"] = df["경주일자"].apply(_parse_date)
    df["순위_num"] = pd.to_numeric(df["순위"], errors="coerce")
    df = compute_position_change(df)
    df = df.dropna(subset=["경주일자_dt", "순위_num", "포지션변화", "초반백분위"]).sort_values(
        ["마호_hrNo", "경주일자_dt"])

    # 과거(이 경주 이전) 레이스들의 평균 포지션변화/초반백분위 — 오직 자기 자신의 과거 기록만 사용
    df["과거평균_포지션변화"] = df.groupby("마호_hrNo")["포지션변화"].transform(
        lambda s: s.shift(1).expanding().mean())
    df["과거평균_초반백분위"] = df.groupby("마호_hrNo")["초반백분위"].transform(
        lambda s: s.shift(1).expanding().mean())
    df["과거경주수"] = df.groupby("마호_hrNo").cumcount()  # 0=첫 출전(과거기록 없음)

    target = df[(df["과거경주수"] >= 2) & df["과거평균_포지션변화"].notna()].copy()
    target["순위비율"] = target["순위_num"] / target["출주두수_실측"]

    min_date = df["경주일자_dt"].min()
    backtest_start = min_date + pd.Timedelta(days=MIN_HISTORY_DAYS)
    target = target[target["경주일자_dt"] >= backtest_start]

    target.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"분석 대상(과거 2회 이상 출전 + 구간기록 보유): {len(target)}건")

    if len(target) < 30:
        print("표본 부족")
        return

    for col, label in [("과거평균_포지션변화", "과거평균 포지션변화(추입성향)"),
                        ("과거평균_초반백분위", "과거평균 초반백분위(선행성향)")]:
        corr = target[[col, "순위비율"]].corr(method="spearman").iloc[0, 1]
        bucket = pd.qcut(target[col], 5, duplicates="drop")
        stats = target.groupby(bucket, observed=True).agg(
            표본수=("순위비율", "count"), 평균순위비율=("순위비율", "mean"),
            승률=("순위_num", lambda s: (s == 1).mean()),
            복승률=("순위_num", lambda s: (s <= 3).mean()),
        ).round(4)
        print(f"\n[{label}] Spearman={corr:.4f}")
        print(stats.to_string())

    # 주로상태별 '추입성향'의 효과 차이 — 가정 없이 각 주로상태 안에서 개별적으로 상관계수 계산
    print("\n[주로상태별 '과거평균 포지션변화'의 효과]")
    for track, g in target.groupby("주로상태"):
        if len(g) < 30:
            print(f"{track}: 표본부족({len(g)}건)")
            continue
        c = g[["과거평균_포지션변화", "순위비율"]].corr(method="spearman").iloc[0, 1]
        print(f"{track}: 표본 {len(g)}건, Spearman={c:.4f}")

    # 선행성향+추입성향 조합 (순위 정규화 동등가중, 레이팅 백테스트와 동일한 방식)
    target["r1"] = target["과거평균_초반백분위"].rank(pct=True)
    target["r2"] = target["과거평균_포지션변화"].rank(pct=True)
    target["조합점수"] = target[["r1", "r2"]].mean(axis=1)
    corr_combo = target[["조합점수", "순위비율"]].corr(method="spearman").iloc[0, 1]
    bucket = pd.qcut(target["조합점수"], 5, duplicates="drop")
    stats = target.groupby(bucket, observed=True).agg(
        표본수=("순위비율", "count"), 평균순위비율=("순위비율", "mean"),
        승률=("순위_num", lambda s: (s == 1).mean()),
        복승률=("순위_num", lambda s: (s <= 3).mean()),
    ).round(4)
    print(f"\n[조합점수(선행성향+추입성향)] Spearman={corr_combo:.4f}")
    print(stats.to_string())


if __name__ == "__main__":
    main()
