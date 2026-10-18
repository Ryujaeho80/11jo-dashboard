"""레이팅 기준 출마등록 판단 지표 — 11조 28두 대상.

공식 레이팅(KRA가 산정)을 1차 지표로 삼는다는 결정에 따라, 아래 3가지를 계산한다:

1. 레이팅 추세 — 최근 경주들의 레이팅이 오르는지 내리는지
2. 출주 간격 — 마지막 출전 이후 며칠 지났는지 (너무 이르거나 너무 뜸하면 flag)
3. 등급 내 상대 위치 — 이 말이 최근 실제로 뛴 등급에서, 부산경남 전체 모집단(타 마방 포함)
   레이팅 분포 대비 어디쯤인지 (백분위)

등급은 소속마 CSV의 고정 스냅샷 라벨 대신, 그 말이 "최근 실제로 뛴 경주의 등급"을 기준으로
삼는다 — 외/국 구분이 실제 레이스 라벨과 소속마 목록 라벨이 다르게 섞여 있어서(예: 외1등급
말이 실제로는 "1등급"이라는 통합 라벨로 뛴 경주도 있음), 실제 뛴 기록이 더 신뢰할 수 있다.

사용법:
    python scripts/analyze_entry_candidates.py
"""
import re
from datetime import date

import pandas as pd

HORSES_CSV = "data/processed/손병철_11조_소속마.csv"
HISTORY_CSV = "data/raw/race_history/race_history_combined.csv"
META_CSV = "data/raw/race_results/race_meta_3.csv"
FIELD_CSV = "data/raw/race_results/race_field_3.csv"
OUT_CSV = "data/processed/entry_candidates_rating_analysis.csv"


def _parse_date(raw) -> pd.Timestamp | None:
    if pd.isna(raw):
        return None
    s = str(raw)
    m = re.match(r"(\d{4})(\d{2})(\d{2})$", s)
    if m:
        return pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"(\d{4})/(\d{2})/(\d{2})", s)
    if m:
        return pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def load_population():
    """부산경남 전체 경주결과(타 마방 포함)를 날짜+등급+거리+주로상태+레이팅으로 정리."""
    meta = pd.read_csv(META_CSV, dtype=str)
    field = pd.read_csv(FIELD_CSV, dtype=str)
    pop = field.merge(meta[["경주일자", "경주번호", "등급", "거리", "주로상태"]],
                       on=["경주일자", "경주번호"], how="left", suffixes=("", "_meta"))
    pop["레이팅_num"] = pd.to_numeric(pop["레이팅"], errors="coerce")
    pop["경주일자_dt"] = pop["경주일자"].apply(_parse_date)
    return pop


def rating_trend(history: pd.DataFrame) -> dict:
    """순(1=최신)이 작을수록 최근 경주. 레이팅 있는 행만으로 추세 판단."""
    h = history.dropna(subset=["레이팅"]).copy()
    h["레이팅"] = pd.to_numeric(h["레이팅"], errors="coerce")
    h = h.dropna(subset=["레이팅"]).sort_values("순")  # 순=1이 가장 최근
    if len(h) == 0:
        return {"최근레이팅": None, "직전레이팅": None, "추세": "레이팅 없음(신마)"}
    latest = h.iloc[0]["레이팅"]
    if len(h) >= 2:
        prev = h.iloc[1]["레이팅"]
        delta = latest - prev
        trend = "상승" if delta > 0 else ("하락" if delta < 0 else "유지")
        return {"최근레이팅": latest, "직전레이팅": prev, "추세": f"{trend}({delta:+.0f})"}
    return {"최근레이팅": latest, "직전레이팅": None, "추세": "데이터부족(1전)"}


def race_interval(history: pd.DataFrame) -> dict:
    h = history.copy()
    h["경주일자_dt"] = h["경주일자"].apply(_parse_date)
    h = h.dropna(subset=["경주일자_dt"]).sort_values("순")
    if len(h) == 0:
        return {"최근출전일": None, "경과일": None, "평균출주간격": None}
    last_date = h.iloc[0]["경주일자_dt"]
    days_since = (pd.Timestamp(date.today()) - last_date).days
    avg_interval = None
    if len(h) >= 2:
        dates_sorted = h["경주일자_dt"].sort_values(ascending=False).reset_index(drop=True)
        # 내림차순(최신→과거) 정렬에서 diff(-1) = dates_sorted[i] - dates_sorted[i+1] = 양수 간격
        diffs = dates_sorted.diff(-1).dropna()
        avg_interval = diffs.dt.days.mean()
    return {"최근출전일": last_date.date().isoformat(), "경과일": days_since,
            "평균출주간격": round(avg_interval, 1) if avg_interval is not None else None}


def _distance_num(raw) -> float | None:
    if pd.isna(raw):
        return None
    m = re.search(r"(\d+)", str(raw))
    return float(m.group(1)) if m else None


def percentile_for_condition(population: pd.DataFrame, grade, distance, track, rating,
                              lookback_months=6, distance_tolerance=200) -> dict:
    """특정 등급+거리+주로상태 조건에서 rating이 모집단 대비 몇 백분위인지.
    class_percentile과 distance_breakdown.py가 공유하는 핵심 로직 — '최근 경주 기준'이든
    '임의의 과거 거리 기준'이든 조건(등급/거리/주로)만 주면 동일하게 계산한다.

    같은 등급·거리라도 주로상태(건조/양호/다습/불량/포화)가 다르면 주로 자체가 다른 셈이라
    비교가 흐려지므로, 표본이 허락하는 한 주로상태까지 맞춘다. 표본 부족 시 단계적으로 완화:
    등급+거리+주로상태 동일 -> 등급+거리 동일(주로 무시) -> 등급+거리 ±200m -> 등급만."""
    if pd.isna(rating) or pd.isna(grade):
        return {"등급내백분위": None, "비교모집단수": 0, "비교기준": None}

    my_rating = float(rating)
    cutoff = pd.Timestamp(date.today()) - pd.Timedelta(days=30 * lookback_months)
    base = population[(population["등급"] == grade) & (population["경주일자_dt"] >= cutoff)].copy()
    base["거리_num"] = base["거리"].apply(_distance_num)
    same_distance = base[base["거리_num"] == distance] if pd.notna(distance) else base

    match_level, pool_ratings = None, pd.Series(dtype=float)

    if track:
        tier = same_distance[same_distance["주로상태"] == track]
        pool_ratings = tier["레이팅_num"].dropna()
        if len(pool_ratings) >= 5:
            match_level = f"등급+거리+주로({track}) 동일"

    if match_level is None:
        pool_ratings = same_distance["레이팅_num"].dropna()
        if len(pool_ratings) >= 5:
            match_level = "등급+거리 동일(주로 무시)"

    if match_level is None and pd.notna(distance):
        tier = base[(base["거리_num"] - distance).abs() <= distance_tolerance]
        pool_ratings = tier["레이팅_num"].dropna()
        if len(pool_ratings) >= 5:
            match_level = f"등급 동일 + 거리 ±{distance_tolerance}m"

    if match_level is None:
        pool_ratings = base["레이팅_num"].dropna()
        match_level = "등급만 동일(거리/주로 무시, 표본 부족)"

    if len(pool_ratings) < 5:
        return {"등급내백분위": None, "비교모집단수": len(pool_ratings), "비교기준": match_level}

    percentile = (pool_ratings < my_rating).mean() * 100
    return {"등급내백분위": round(percentile, 1), "비교모집단수": len(pool_ratings),
            "비교기준": match_level,
            "등급내평균레이팅": round(pool_ratings.mean(), 1),
            "등급내최고레이팅": round(pool_ratings.max(), 1)}


def class_percentile(history: pd.DataFrame, population: pd.DataFrame, current_rating,
                      lookback_months=6, distance_tolerance=200) -> dict:
    """등급+거리는 '최근 실제로 뛴 경주' 기준, 레이팅은 소속마 목록의 현재값을 쓴다.
    KRA는 경주 없이도 주기적으로 레이팅을 재산정하므로 소속마 목록 쪽이 더 최신이다."""
    h = history.copy()
    h["경주일자_dt"] = h["경주일자"].apply(_parse_date)
    h = h.dropna(subset=["경주일자_dt", "등급"]).sort_values("순")
    if len(h) == 0 or pd.isna(current_rating):
        return {"최근출전등급": None, "최근출전거리": None, "최근주로상태": None,
                "등급내백분위": None, "비교모집단수": 0}

    recent_grade = h.iloc[0]["등급"]
    recent_distance = _distance_num(h.iloc[0]["거리"])
    # 말 이력 쪽은 "건조(4%)"처럼 함수율이 붙어있고, 모집단(race_meta) 쪽은 "건조"만 있음 — 범주만 비교
    raw_track = h.iloc[0]["주로"] if "주로" in h.columns else None
    recent_track = re.match(r"([^\(]+)", raw_track).group(1).strip() if pd.notna(raw_track) and raw_track else None

    result = percentile_for_condition(population, recent_grade, recent_distance, recent_track,
                                       current_rating, lookback_months, distance_tolerance)
    return {"최근출전등급": recent_grade, "최근출전거리": recent_distance,
            "최근주로상태": recent_track, **result}


def interchange_summary(history: pd.DataFrame) -> dict:
    """타 경마장(서울/제주/영천)과의 교류경주 참가·우승 이력 — 홈 모집단 비교를 넘어선 신호."""
    ic = history[history.get("교류경주", "") == "Y"]
    if len(ic) == 0:
        return {"교류경주참가": 0, "교류경주우승": 0, "교류경주개최지": ""}
    wins = (ic["순위"] == "1").sum()
    venues = ",".join(sorted(ic["개최지"].dropna().unique()))
    return {"교류경주참가": len(ic), "교류경주우승": int(wins), "교류경주개최지": venues}


def main():
    horses = pd.read_csv(HORSES_CSV, dtype=str)
    history_all = pd.read_csv(HISTORY_CSV, dtype=str)
    population = load_population()

    rows = []
    for _, h in horses.iterrows():
        hr_no, hr_name = h["마번"], h["마명"]
        hist = history_all[history_all["마번"] == hr_no]

        row = {"마번": hr_no, "마명": hr_name, "소속마목록등급": h["등급"], "소속마목록레이팅": h["레이팅"]}
        row.update(rating_trend(hist))
        row.update(race_interval(hist))
        current_rating = pd.to_numeric(h["레이팅"], errors="coerce")
        row.update(class_percentile(hist, population, current_rating))
        row.update(interchange_summary(hist))
        rows.append(row)

    result = pd.DataFrame(rows)
    result.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    cols_show = ["마명", "최근출전등급", "최근출전거리", "최근주로상태", "최근레이팅", "추세",
                 "등급내백분위", "비교모집단수", "비교기준", "경과일", "교류경주참가", "교류경주우승"]
    print(result[cols_show].to_string(index=False))
    print(f"\n-> {OUT_CSV}")


if __name__ == "__main__":
    main()
