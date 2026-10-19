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
from pathlib import Path

import numpy as np
import pandas as pd

HORSES_CSV = "data/processed/손병철_11조_소속마.csv"
HISTORY_CSV = "data/raw/race_history/race_history_combined.csv"
RACE_RESULTS_DIR = "data/raw/race_results"
# 모집단에 포함할 meet 코드. 3=부산경남(홈), 4=영천.
# 2026-10-20 확인: 현재 서울이 영천 참가를 안 해서 영천 경주는 사실상 전부 부산경남 말들끼리의
# 경주라 "원정"이 아니라 장소만 다른 부산경남 경주로 보고 같이 합친다. 서울이 영천에 복귀하면
# 방문마 필터([서] 접두사, load_population 참고)가 그 말들을 자동으로 걸러낸다.
POPULATION_MEETS = ["3", "4"]
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


def grade_parts(label):
    """등급 라벨을 (계열, 종류)로 분해. 계열: '국'/'혼'/''(무접두 1,2등급), 종류: 등급숫자 또는 'OPEN'."""
    if pd.isna(label):
        return None, None
    s = str(label)
    m = re.match(r"^(국|혼)?(\d+)등급$", s)
    if m:
        return m.group(1) or "", m.group(2)
    m = re.match(r"^(국|혼)?OPEN$", s)
    if m:
        return m.group(1) or "", "OPEN"
    return None, None


def build_grade_ceilings(reference_pop: pd.DataFrame) -> dict:
    """실측 데이터로 '국'/'혼' 계열별 등급-레이팅상한(ceiling) 사다리를 만든다.

    2026-10-20 사용자 확인: OPEN은 등급이 아니라 '등급 제한 없이 뛰는 경주'다(실제로 같은
    국OPEN 경주 안에서도 레이팅이 55~109, 31~50처럼 경주마다 들쭉날쭉 — 반면 일반 등급은
    날짜가 달라도 항상 같은 밴드). 그래서 OPEN에서 뛴 말을 그 등급 라벨 그대로 비교군에
    묶으면 실제 실력이 전혀 다른 말들이 섞인다. 번호등급(1~6등급)은 레이팅 상한(ceiling)으로
    정의되는 구조로 보이므로(등급별 최소값은 거의 다 바닥값 23 근처로 공통, 최대값만 등급마다
    뚜렷이 다름) — 이 상한표로 OPEN 말을 실제 레이팅에 맞는 번호등급으로 재분류한다."""
    df = reference_pop.dropna(subset=["등급"])
    if len(df) == 0:
        return {"국": [], "혼": []}
    parts = df["등급"].map(grade_parts)
    families = parts.map(lambda p: p[0])
    kinds = parts.map(lambda p: p[1])
    numbered = df[kinds.notna() & (kinds != "OPEN") & df["레이팅_num"].notna()].copy()
    numbered["_계열"] = families[numbered.index]
    numbered["_종류"] = kinds[numbered.index]
    if len(numbered) == 0:
        return {"국": [], "혼": []}
    ceilings = numbered.groupby(["_계열", "_종류"])["레이팅_num"].max()

    ladders = {}
    for family in ("국", "혼"):
        rungs = {}
        for (fam, num), ceil in ceilings.items():
            if fam == family or fam == "":  # 무접두 1,2등급은 국/혼 공용 최상위
                rungs[f"{fam}{num}등급"] = ceil
        ladders[family] = sorted(rungs.items(), key=lambda x: x[1])
    return ladders


def infer_open_grade(rating, grade_label, ladders: dict) -> str:
    """OPEN 등급 라벨 하나를 실제 레이팅에 맞는 번호등급으로 치환(단일값용). 번호등급은 그대로 반환."""
    if pd.isna(grade_label):
        return grade_label
    family, kind = grade_parts(grade_label)
    if kind != "OPEN" or pd.isna(rating):
        return grade_label
    ladder = ladders.get(family or "", [])
    if not ladder:
        return grade_label
    ceilings = [c for _, c in ladder]
    labels = [l for l, _ in ladder]
    idx = int(np.clip(np.searchsorted(ceilings, float(rating), side="left"), 0, len(labels) - 1))
    return labels[idx]


def attach_matched_grade(df: pd.DataFrame, ladders: dict) -> pd.Series:
    """df 전체에 대해 OPEN 라벨을 레이팅 기준 번호등급으로 치환한 '등급' Series를 반환(벡터화).
    df 자체는 변경하지 않는다 — 호출부에서 새 컬럼으로 붙여 쓴다."""
    out = df["등급"].astype(object).copy()
    for g in [g for g in df["등급"].dropna().unique()]:
        family, kind = grade_parts(g)
        if kind != "OPEN":
            continue
        ladder = ladders.get(family or "", [])
        if not ladder:
            continue
        mask = (df["등급"] == g) & df["레이팅_num"].notna()
        if not mask.any():
            continue
        ceilings = np.array([c for _, c in ladder])
        labels = [l for l, _ in ladder]
        ratings = df.loc[mask, "레이팅_num"].to_numpy(dtype=float)
        idx = np.clip(np.searchsorted(ceilings, ratings, side="left"), 0, len(labels) - 1)
        out.loc[mask] = [labels[i] for i in idx]
    return out


def home_filter(h: pd.DataFrame) -> pd.DataFrame:
    """'홈(부산경남) 조건'으로 취급할 행만 남긴다 — 교류경주라도 영천(meet=4)은 원정으로
    치지 않는다. 2026-10-20 사용자 확인: 현재 서울이 영천 참가를 안 해서 영천 경주는 사실상
    전부 부산경남 말들끼리의 경주다(POPULATION_MEETS 선언부 설명과 동일한 근거). 서울/제주 등
    실제 타지역 원정만 제외한다. (조건을 만족하는 행이 하나도 없으면 원본을 그대로 반환.)"""
    if "교류경주" not in h.columns:
        return h
    is_away = h["교류경주"] == "Y"
    if "개최지" in h.columns:
        is_away = is_away & (h["개최지"] != "영천")
    home_only = h[~is_away]
    return home_only if len(home_only) > 0 else h


def load_population():
    """부산경남 '소속' 말들의 경주결과(타 마방 포함)를 날짜+등급+거리+주로상태+레이팅으로 정리.

    대상경주(스테이크스)에는 서울/제주 등 타 지역 소속마가 교류경주로 참가하는데, 이런 말은
    마명 앞에 "[서]" 같은 지역 접두사가 붙는다(2026-10-20 사용자 지적으로 발견). 평소 일반
    출마투표는 그 지역 소속마끼리만 하므로, 이 접두사가 붙은 방문마는 '우리 말들이 평소
    실제로 맞붙을 상대 모집단'에서 제외해야 한다 — 안 그러면 혼OPEN처럼 대상경주 비중이 큰
    등급에서 모집단 대부분이 방문마로 채워져 비교 자체가 왜곡된다(판타스틱밸류 사례: 17두
    중 13두가 서울말이었음). 조교사 명단 대조 방식은 활동 조교사 명단을 수동으로 관리해야
    해서 오히려 부정확했고(활동 중인 임성실 등을 누락), 마명 접두사가 KRA가 직접 표기하는
    더 정확한 신호다.

    2026-10-20부터 meet=4(영천)도 합친다 — 현재 서울이 영천 참가를 안 해서 영천 경주는
    사실상 전부 부산경남 말들끼리의 경주다(POPULATION_MEETS 선언부 설명 참고). meet별로
    따로 merge한 뒤 합쳐서, 혹시 모를 (경주일자,경주번호) 충돌을 피한다."""
    pop_parts = []
    for meet in POPULATION_MEETS:
        meta_path = Path(RACE_RESULTS_DIR) / f"race_meta_{meet}.csv"
        field_path = Path(RACE_RESULTS_DIR) / f"race_field_{meet}.csv"
        if not meta_path.exists() or not field_path.exists():
            continue
        meta = pd.read_csv(meta_path, dtype=str)
        field = pd.read_csv(field_path, dtype=str)
        merged = field.merge(meta[["경주일자", "경주번호", "등급", "거리", "주로상태"]],
                              on=["경주일자", "경주번호"], how="left", suffixes=("", "_meta"))
        merged["수집meet"] = meet
        pop_parts.append(merged)
    pop = pd.concat(pop_parts, ignore_index=True)
    pop = pop[~pop["마명"].str.match(r"^\[.\]", na=False)]
    pop["레이팅_num"] = pd.to_numeric(pop["레이팅"], errors="coerce")
    pop["경주일자_dt"] = pop["경주일자"].apply(_parse_date)
    ladders = build_grade_ceilings(pop)
    pop["등급_매칭"] = attach_matched_grade(pop, ladders)
    return pop


def rating_trend(history: pd.DataFrame) -> dict:
    """순(1=최신)이 작을수록 최근 경주. 레이팅 있는 행만으로 추세 판단."""
    h = history.dropna(subset=["레이팅"]).copy()
    h["레이팅"] = pd.to_numeric(h["레이팅"], errors="coerce")
    # "순"은 문자열 컬럼이라 기본 정렬은 사전식("11" < "2")이 됨 — 반드시 숫자로 변환해서 정렬.
    h = h.dropna(subset=["레이팅"]).sort_values("순", key=lambda s: pd.to_numeric(s, errors="coerce"))  # 순=1이 가장 최근
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
    h = h.dropna(subset=["경주일자_dt"]).sort_values("순", key=lambda s: pd.to_numeric(s, errors="coerce"))
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
        return {"등급내백분위": None, "비교모집단수": 0, "비교기준": None, "비교등급": None}

    my_rating = float(rating)
    ladders = build_grade_ceilings(population)
    matched_grade = infer_open_grade(my_rating, grade, ladders)
    cutoff = pd.Timestamp(date.today()) - pd.Timedelta(days=30 * lookback_months)
    base = population[(population["등급_매칭"] == matched_grade) & (population["경주일자_dt"] >= cutoff)].copy()
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
        return {"등급내백분위": None, "비교모집단수": len(pool_ratings), "비교기준": match_level,
                "비교등급": matched_grade}

    percentile = (pool_ratings < my_rating).mean() * 100
    return {"등급내백분위": round(percentile, 1), "비교모집단수": len(pool_ratings),
            "비교기준": match_level,
            "비교등급": matched_grade,
            "등급내평균레이팅": round(pool_ratings.mean(), 1),
            "등급내최고레이팅": round(pool_ratings.max(), 1)}


def class_percentile(history: pd.DataFrame, population: pd.DataFrame, current_rating,
                      lookback_months=6, distance_tolerance=200) -> dict:
    """등급+거리는 '최근 실제로 뛴 경주' 기준, 레이팅은 소속마 목록의 현재값을 쓴다.
    KRA는 경주 없이도 주기적으로 레이팅을 재산정하므로 소속마 목록 쪽이 더 최신이다."""
    h = history.copy()
    h["경주일자_dt"] = h["경주일자"].apply(_parse_date)
    h = h.dropna(subset=["경주일자_dt", "등급"]).sort_values("순", key=lambda s: pd.to_numeric(s, errors="coerce"))
    if len(h) == 0 or pd.isna(current_rating):
        return {"최근출전등급": None, "최근출전거리": None, "최근주로상태": None,
                "등급내백분위": None, "비교모집단수": 0}

    # population(모집단)은 부산경남+영천(meet=3,4) 데이터로 구성되므로, 비교 기준이 되는
    # 등급/거리/주로도 반드시 그 범위 내 최근 경주에서 뽑아야 한다 — 그렇지 않으면 말의
    # '전체 최근 경주'가 서울/제주 교류경주일 때 모집단 매칭 기준 자체가 어긋난다
    # (2026-10-18 발견: 판타스틱밸류가 서울 교류경주 등급으로 매칭되어 실제 부산경남
    # 성적과 다른 조건으로 비교되고 있었음). home_filter()가 영천은 원정으로 치지 않는다.
    h = home_filter(h)

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
