"""11조 각 말마다, 같은 등급+거리+주로상태 모집단 안의 상대마 전체를 백테스트로 검증된
조합점수(백분위+추세)로 순위 매겨서 보여준다 — 타 마방 포함, 실제 데이터 기반.

Task #6 백테스트에서 '사전백분위 + 레이팅추세' 조합이 가장 강한 신호임을 확인했으므로
(단독 -0.17/-0.22 대비 조합 -0.25), 그 조합을 그대로 상대마 비교에도 적용한다.

사용법:
    python scripts/rival_comparison.py
"""
import pandas as pd

from analyze_entry_candidates import (
    HORSES_CSV, _distance_num, _parse_date, build_grade_ceilings, infer_open_grade, load_population,
)

OUT_CSV = "data/processed/rival_comparison.csv"
LOOKBACK_MONTHS = 6


def population_with_trend():
    """모집단 전체에 대해 레이팅추세(직전 출전 대비)를 계산 — 같은 말의 과거 기록만 사용.
    레이팅이 아직 없는 말(신마·최하위군)도 포함한다 — 순위 비교엔 못 쓰지만 "비교군에 같이
    뛰는 말"로서 상대마 비교 표 맨 아래에 순위없이 보여주기 위함(2026-10-20 사용자 요청)."""
    pop = load_population()
    pop["거리_num"] = pop["거리"].apply(_distance_num)
    pop = pop.dropna(subset=["경주일자_dt", "등급"]).sort_values(
        ["마호_hrNo", "경주일자_dt"])
    pop["직전레이팅"] = pop.groupby("마호_hrNo")["레이팅_num"].shift(1)
    pop["레이팅추세"] = pop["레이팅_num"] - pop["직전레이팅"]
    # 각 말의 '가장 최근' 기록만 남김 (지금 시점 비교이므로)
    latest = pop.sort_values("경주일자_dt").groupby("마호_hrNo").tail(1).copy()
    return latest


def main():
    horses = pd.read_csv(HORSES_CSV, dtype=str)
    history_all = pd.read_csv("data/raw/race_history/race_history_combined.csv", dtype=str)
    latest_pop = population_with_trend()

    cutoff = pd.Timestamp.today() - pd.Timedelta(days=30 * LOOKBACK_MONTHS)
    latest_pop = latest_pop[latest_pop["경주일자_dt"] >= cutoff]
    # OPEN은 등급이 아니라 '등급 제한 없이 뛰는 경주'라 레이팅이 들쭉날쭉이므로(2026-10-20
    # 확인), 번호등급(1~6등급) 레이팅 상한표로 재분류한 뒤 그 기준으로 비교군을 묶는다.
    # latest_pop(말 1두당 1행)보다 표본이 큰 전체 모집단으로 상한표를 만들어야 더 안정적이고,
    # load_population()이 "등급_매칭" 컬럼을 만들 때 쓴 것과 동일한 기준이라 일관성도 맞는다.
    ladders = build_grade_ceilings(load_population())

    all_rows = []
    for _, h in horses.iterrows():
        hr_no, hr_name = h["마번"], h["마명"]
        hist = history_all[history_all["마번"] == hr_no]
        hist = hist.dropna(subset=["등급"]) if "등급" in hist.columns else hist
        if len(hist) == 0:
            continue
        hist_sorted = hist.copy()
        hist_sorted["경주일자_dt"] = hist_sorted["경주일자"].apply(_parse_date)
        hist_sorted = hist_sorted.dropna(subset=["경주일자_dt"]).sort_values(
            "순", key=lambda s: pd.to_numeric(s, errors="coerce"))
        if len(hist_sorted) == 0:
            continue

        # 모집단(latest_pop)은 부산경남(meet=3) 데이터로만 만들어지므로, 비교 기준이 되는
        # '내 등급/거리/주로'도 반드시 부산경남 내 최근 경주에서 뽑아야 한다. 안 그러면
        # 말의 '전체 최근 경주'가 서울/제주 교류경주일 때 그 말이 자기 모집단에서 빠지는
        # 버그가 생김(2026-10-18 발견: 판타스틱밸류가 서울 교류경주 등급 기준으로 조회되어
        # 정작 부산경남 모집단엔 다른 등급으로 들어가있어 본인이 검색 안 됨).
        home_only = hist_sorted[hist_sorted["교류경주"] != "Y"]
        if len(home_only) > 0:
            hist_sorted = home_only

        my_grade_raw = hist_sorted.iloc[0]["등급"]
        my_rating = pd.to_numeric(h["레이팅"], errors="coerce")  # 소속마 목록의 현재 레이팅(최신)
        my_grade = infer_open_grade(my_rating, my_grade_raw, ladders)
        my_distance = _distance_num(hist_sorted.iloc[0]["거리"])
        my_track_raw = hist_sorted.iloc[0]["주로"]
        my_track = str(my_track_raw).split("(")[0] if pd.notna(my_track_raw) else None

        bucket = latest_pop[latest_pop["등급_매칭"] == my_grade].copy()
        bucket_label = f"{my_grade}" + (f"(OPEN환산, 원등급 {my_grade_raw})" if my_grade != my_grade_raw else "")
        if my_distance is not None:
            same_d = bucket[bucket["거리_num"] == my_distance]
            if len(same_d) >= 5:
                bucket = same_d
                bucket_label += f" / {int(my_distance)}M"
                if my_track:
                    same_dt = bucket[bucket["주로상태"] == my_track]
                    if len(same_dt) >= 5:
                        bucket = same_dt
                        bucket_label += f" / {my_track}"

        if len(bucket) < 3:
            continue

        bucket = bucket.copy()
        has_rating = bucket["레이팅_num"].notna()
        bucket["백분위"] = bucket["레이팅_num"].rank(pct=True) * 100
        bucket["추세백분위"] = bucket["레이팅추세"].rank(pct=True, na_option="bottom") * 100
        bucket["조합점수"] = bucket[["백분위", "추세백분위"]].mean(axis=1)
        # 레이팅 없는 말(신마·최하위군)은 백분위/조합점수를 아예 매길 수 없으므로 전부 공란 처리 —
        # 정렬 시 판다스 기본 동작(NaN이 끝으로 감)으로 자동으로 맨 아래에 깔린다.
        bucket.loc[~has_rating, ["백분위", "추세백분위", "조합점수"]] = pd.NA
        bucket = bucket.sort_values("조합점수", ascending=False, na_position="last").reset_index(drop=True)
        ranked = bucket["조합점수"].notna()
        bucket["상대순위"] = pd.NA
        bucket.loc[ranked, "상대순위"] = range(1, int(ranked.sum()) + 1)
        bucket["비교모집단규모"] = int(ranked.sum())
        bucket["비교기준"] = bucket_label
        bucket["기준말_마번"] = hr_no
        bucket["기준말_마명"] = hr_name
        bucket["우리말여부"] = bucket["마호_hrNo"] == hr_no

        cols = ["기준말_마명", "기준말_마번", "비교기준", "비교모집단규모", "상대순위",
                "마명", "마호_hrNo", "조교사명", "마주명", "레이팅_num", "레이팅추세",
                "백분위", "조합점수", "우리말여부"]
        all_rows.append(bucket[cols])

    if not all_rows:
        print("비교 가능한 말이 없습니다 (모집단 부족)")
        return

    result = pd.concat(all_rows, ignore_index=True)
    result.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"{result['기준말_마명'].nunique()}두에 대한 상대마 비교표 생성 -> {OUT_CSV}")

    # 우리 말들이 각 비교군에서 몇 등인지 요약
    summary = result[result["우리말여부"]][
        ["기준말_마명", "비교기준", "비교모집단규모", "상대순위", "조합점수"]
    ].sort_values("상대순위")
    print("\n우리 말들의 상대마 비교군 내 순위:")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
