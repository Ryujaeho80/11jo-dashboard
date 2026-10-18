"""레이스 편성을 더 똑똑하게 하기 위한 말별 요약 인사이트 3가지.

전부 이미 검증된 계산(percentile_for_condition, 포지션변화)을 재사용 — 새로운 예측 주장을
추가하는 게 아니라, 이미 나온 숫자들을 "편성에 바로 쓸 수 있는 형태"로 요약하는 것.

1. 최적거리 — 현재 등급에서(없으면 가장 최근 등급) 등급내백분위가 가장 높은 거리.
   "데이터가 쌓이고 등급이 정해지면" 신뢰도가 올라가므로, 비교 가능한 거리가 1개뿐이면
   그 사실을 명시한다(아직 판단하기 이르다는 뜻).
2. 양면형(선행+추입 둘 다) — 과거 경주에서 초반에 앞서서 좋은 성적을 낸 적도 있고,
   후방에서 치고 올라와 좋은 성적을 낸 적도 있는 말. 둘 중 하나만 되는 말과 구분된다.
3. 신경써야 할 점 — 레이팅 하락세, 출주간격 부적정, 현재등급 하위권, 러닝스타일 판단
   표본부족 등을 한 번에 모아서 보여줌. 전부 이미 계산된 값의 조합일 뿐 새 지표 아님.

사용법:
    python scripts/horse_insights.py
"""
import pandas as pd

from analyze_entry_candidates import HORSES_CSV
from backtest_running_style import compute_position_change

DISTANCE_CSV = "data/processed/distance_breakdown.csv"
SCORE_CSV = "data/processed/final_entry_score.csv"
FIELD_CSV = "data/raw/race_results/race_field_3.csv"
OUT_CSV = "data/processed/horse_insights.csv"

FRONT_THRESHOLD = 0.6   # 초반백분위 이 이상이면 '선행 시도'
CLOSER_EARLY_MAX = 0.4  # 초반백분위 이 이하이면서
CLOSER_GAIN_MIN = 0.15  # 포지션변화가 이 이상이면 '추입 시도'
GOOD_RESULT_RANK = 3    # 3착 이내를 '성공'으로 봄


def optimal_distance(dist_rows: pd.DataFrame, current_grade) -> dict:
    if len(dist_rows) == 0:
        return {"최적거리": None, "최적거리백분위": None, "최적거리근거": "경주이력 없음"}

    at_current = dist_rows[dist_rows["등급"] == current_grade]
    pool, basis = (at_current, "현재등급 기준") if len(at_current) > 0 else (dist_rows, "현재등급 데이터 없어 과거등급 포함")
    valid = pool.dropna(subset=["등급내백분위"])
    if len(valid) == 0:
        return {"최적거리": None, "최적거리백분위": None, "최적거리근거": "백분위 계산 가능한 거리 없음"}

    best = valid.loc[valid["등급내백분위"].idxmax()]
    note = basis
    if len(valid) == 1:
        note += " — 비교 가능한 거리 1개뿐(판단 보류 권장, 데이터 더 쌓이면 재평가)"
    return {"최적거리": int(best["거리"]), "최적거리백분위": best["등급내백분위"], "최적거리근거": note}


def style_versatility(my_races: pd.DataFrame) -> dict:
    races = my_races.dropna(subset=["초반백분위", "순위_num"])
    if len(races) == 0:
        return {"양면형": False, "선행성공": 0, "추입성공": 0, "분석경주수": 0}

    front_success = races[(races["초반백분위"] >= FRONT_THRESHOLD) & (races["순위_num"] <= GOOD_RESULT_RANK)]
    closer_success = races[(races["초반백분위"] <= CLOSER_EARLY_MAX) &
                            (races["포지션변화"] >= CLOSER_GAIN_MIN) & (races["순위_num"] <= GOOD_RESULT_RANK)]
    return {
        "양면형": len(front_success) > 0 and len(closer_success) > 0,
        "선행성공": len(front_success), "추입성공": len(closer_success), "분석경주수": len(races),
    }


def attention_flags(row: dict, versatility: dict) -> list[str]:
    flags = []
    trend = row.get("레이팅추세_num")
    if pd.notna(trend) and trend < 0:
        flags.append(f"레이팅 하락세({trend:+.0f})")

    days = row.get("경과일")
    if pd.notna(days):
        if days < 21:
            flags.append(f"출주간격 짧음({int(days)}일)")
        elif days > 60:
            flags.append(f"장기 미출전({int(days)}일)")

    pct = row.get("등급내백분위")
    if pd.notna(pct) and pct < 25:
        flags.append(f"현재등급 하위권({pct:.0f}%ile)")

    if versatility["분석경주수"] < 3:
        flags.append(f"러닝스타일 판단 표본부족({versatility['분석경주수']}전)")

    return flags


def main():
    horses = pd.read_csv(HORSES_CSV, dtype=str)
    scores = pd.read_csv(SCORE_CSV, dtype={"마번": str})
    distances = pd.read_csv(DISTANCE_CSV, dtype={"마번": str})

    field = pd.read_csv(FIELD_CSV, dtype=str)
    field["순위_num"] = pd.to_numeric(field["순위"], errors="coerce")
    field = compute_position_change(field)

    rows = []
    for _, h in horses.iterrows():
        hr_no, hr_name = h["마번"], h["마명"]
        score_row = scores[scores["마번"].astype(str) == str(hr_no)]
        current_grade = (score_row.iloc[0].get("최근출전등급") if len(score_row) > 0
                          else None) or h["등급"]

        d_rows = distances[distances["마번"].astype(str) == str(hr_no)]
        opt = optimal_distance(d_rows, current_grade)

        my_races = field[field["마호_hrNo"] == hr_no]
        vers = style_versatility(my_races)

        row = {"마번": hr_no, "마명": hr_name, "현재등급": current_grade, **opt,
               "양면형": vers["양면형"], "선행성공횟수": vers["선행성공"],
               "추입성공횟수": vers["추입성공"], "러닝스타일분석경주수": vers["분석경주수"]}

        score_dict = score_row.iloc[0].to_dict() if len(score_row) > 0 else {}
        flags = attention_flags(score_dict, vers)
        row["신경써야할점"] = " / ".join(flags) if flags else ""
        rows.append(row)

    result = pd.DataFrame(rows)
    result.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print(f"{len(result)}두 인사이트 산출 -> {OUT_CSV}")
    print(f"양면형(선행+추입 둘 다 성공 이력): {result['양면형'].sum()}두")
    has_flags = (result["신경써야할점"] != "").sum()
    print(f"주의사항 있는 말: {has_flags}두")


if __name__ == "__main__":
    main()
