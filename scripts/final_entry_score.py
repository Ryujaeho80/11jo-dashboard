"""11조 28두 최종 출마등록 점수 — 백테스트로 검증된 4개 지표를 그대로 결합.

채택 근거 (scripts/backtest_final_combo.py 결과):
- 레이팅조합(백분위+추세) 단독: Spearman -0.2520
- 러닝스타일조합(선행+추입) 단독: Spearman -0.3172
- 4지표 전체조합: Spearman -0.3175 (러닝스타일 단독과 사실상 동일 — 억지 개선 아님, 정보량만 더 많음)

가중치는 전부 동등(순위 정규화 후 단순평균) — 임의로 가중치를 부여하지 않는다는 원칙 유지.

사용법:
    python scripts/final_entry_score.py
"""
import pandas as pd

from analyze_entry_candidates import (
    HORSES_CSV, HISTORY_CSV, class_percentile, interchange_summary,
    race_interval, rating_trend, load_population, _distance_num, _parse_date,
)
from backtest_running_style import compute_position_change

FIELD_CSV = "data/raw/race_results/race_field_3.csv"
META_CSV = "data/raw/race_results/race_meta_3.csv"
OUT_CSV = "data/processed/final_entry_score.csv"


def running_style_for_horse(hr_no: str, field_pop: pd.DataFrame) -> dict:
    """이 말의 '지금까지 전체' 경주 이력에서 선행성향/추입성향 평균 (point-in-time 제약 없음 — 현재 시점 평가)."""
    mine = field_pop[field_pop["마호_hrNo"] == hr_no]
    if len(mine) == 0:
        return {"선행성향": None, "추입성향": None, "구간기록보유경주수": 0}
    avg_early = mine["초반백분위"].mean()
    avg_change = mine["포지션변화"].mean()
    return {"선행성향": avg_early, "추입성향": avg_change, "구간기록보유경주수": len(mine)}


def main():
    horses = pd.read_csv(HORSES_CSV, dtype=str)
    history_all = pd.read_csv(HISTORY_CSV, dtype=str)
    population = load_population()

    field_pop = pd.read_csv(FIELD_CSV, dtype=str)
    field_pop["순위_num"] = pd.to_numeric(field_pop["순위"], errors="coerce")
    field_pop = compute_position_change(field_pop)

    rows = []
    for _, h in horses.iterrows():
        hr_no, hr_name = h["마번"], h["마명"]
        hist = history_all[history_all["마번"] == hr_no]

        row = {"마번": hr_no, "마명": hr_name, "소속마목록등급": h["등급"]}
        row.update(rating_trend(hist))
        row.update(race_interval(hist))
        current_rating = pd.to_numeric(h["레이팅"], errors="coerce")
        row.update(class_percentile(hist, population, current_rating))
        row.update(interchange_summary(hist))
        row.update(running_style_for_horse(hr_no, field_pop))
        rows.append(row)

    result = pd.DataFrame(rows)

    # 4개 지표 점수화 — 레이팅추세는 이미 숫자(상승폭), 등급내백분위도 0~100
    def _trend_num(s):
        import re
        m = re.search(r"([+-]\d+)", str(s))
        return float(m.group(1)) if m else None
    result["레이팅추세_num"] = result["추세"].apply(_trend_num)

    scorable = result.dropna(subset=["등급내백분위", "레이팅추세_num", "선행성향", "추입성향"]).copy()
    excluded = result[~result["마번"].isin(scorable["마번"])]

    for col in ["등급내백분위", "레이팅추세_num", "선행성향", "추입성향"]:
        scorable[f"r_{col}"] = scorable[col].rank(pct=True)
    scorable["최종점수"] = scorable[
        ["r_등급내백분위", "r_레이팅추세_num", "r_선행성향", "r_추입성향"]
    ].mean(axis=1) * 100

    scorable = scorable.sort_values("최종점수", ascending=False)
    result_final = pd.concat([scorable, excluded], ignore_index=True)
    result_final.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    cols_show = ["마명", "소속마목록등급", "최근출전등급", "등급내백분위", "추세",
                 "선행성향", "추입성향", "경과일", "최종점수"]
    print(f"점수 산출 완료: {len(scorable)}두 (4지표 전부 계산 가능) / 제외: {len(excluded)}두 (신마 등 데이터 부족)")
    print("\n=== 11조 최종 출마등록 점수 (높을수록 유리) ===")
    print(scorable[cols_show].round(1).to_string(index=False))

    if len(excluded) > 0:
        print(f"\n제외된 말: {', '.join(excluded['마명'].tolist())}")


if __name__ == "__main__":
    main()
