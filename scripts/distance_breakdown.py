"""11조 각 말의 '거리x등급별' 성적/백분위 분해.

처음엔 거리로만 묶었는데, 같은 거리라도 하위등급 때 뛴 기록과 승급 후 상위등급 때 뛴 기록이
섞이면 "하위군에서 압도적으로 이기다가 승급한" 케이스를 못 구분한다는 지적을 받아 수정함
— 거리와 등급을 함께 묶어서, 승급 전/후 성적이 각각 별도 행으로 나오도록 바꿨다.

각 (말, 거리, 등급) 조합마다: 출전횟수, 평균순위비율, 그 조건에서 가장 최근 뛴 레이팅,
그리고 그 등급+거리(+주로상태) 모집단 대비 백분위를 계산한다.

사용법:
    python scripts/distance_breakdown.py
"""
import pandas as pd

from analyze_entry_candidates import (
    HORSES_CSV, HISTORY_CSV, _distance_num, _parse_date, load_population, percentile_for_condition,
)

OUT_CSV = "data/processed/distance_breakdown.csv"


def main():
    horses = pd.read_csv(HORSES_CSV, dtype=str)
    history_all = pd.read_csv(HISTORY_CSV, dtype=str)
    population = load_population()

    rows = []
    for _, h in horses.iterrows():
        hr_no, hr_name = h["마번"], h["마명"]
        hist = history_all[history_all["마번"] == hr_no].copy()
        if len(hist) == 0:
            continue
        hist["경주일자_dt"] = hist["경주일자"].apply(_parse_date)
        hist["거리_num"] = hist["거리"].apply(_distance_num)
        hist["레이팅_num"] = pd.to_numeric(hist["레이팅"], errors="coerce")
        hist["순위_num"] = pd.to_numeric(hist["순위"], errors="coerce")
        hist["출주두수_num"] = pd.to_numeric(hist["출주두수"], errors="coerce")
        hist = hist.dropna(subset=["경주일자_dt", "거리_num", "등급"]).sort_values("경주일자_dt")

        # 거리 '+' 등급을 함께 묶는다 — 같은 거리라도 승급 전/후는 별개 행으로 분리
        for (distance, grade), g in hist.groupby(["거리_num", "등급"]):
            g = g.sort_values("경주일자_dt")
            latest = g.iloc[-1]  # 이 거리+등급 조합에서 가장 최근 경주
            n_starts = len(g)
            avg_rank_ratio = (g["순위_num"] / g["출주두수_num"]).mean()
            best_rank = g["순위_num"].min()

            raw_track = latest.get("주로")
            track = str(raw_track).split("(")[0] if pd.notna(raw_track) and raw_track else None
            rating = latest["레이팅_num"]

            pct_result = percentile_for_condition(population, grade, distance, track, rating)

            rows.append({
                "마번": hr_no, "마명": hr_name, "거리": int(distance), "등급": grade,
                "출전횟수": n_starts, "평균순위비율": round(avg_rank_ratio, 3) if pd.notna(avg_rank_ratio) else None,
                "최고순위": int(best_rank) if pd.notna(best_rank) else None,
                "최근출전일": latest["경주일자_dt"].date().isoformat(),
                "최근레이팅": rating if pd.notna(rating) else None,
                "등급내백분위": pct_result.get("등급내백분위"),
                "비교모집단수": pct_result.get("비교모집단수"),
                "비교기준": pct_result.get("비교기준"),
            })

    result = pd.DataFrame(rows).sort_values(["마명", "거리", "최근출전일"])
    result.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"{result['마명'].nunique()}두, {len(result)}개 (말x거리) 조합 -> {OUT_CSV}")


if __name__ == "__main__":
    main()
