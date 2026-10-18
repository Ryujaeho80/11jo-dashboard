"""11조 각 말마다, 같은 등급+거리+주로상태 모집단 안의 상대마 전체를 백테스트로 검증된
조합점수(백분위+추세)로 순위 매겨서 보여준다 — 타 마방 포함, 실제 데이터 기반.

Task #6 백테스트에서 '사전백분위 + 레이팅추세' 조합이 가장 강한 신호임을 확인했으므로
(단독 -0.17/-0.22 대비 조합 -0.25), 그 조합을 그대로 상대마 비교에도 적용한다.

사용법:
    python scripts/rival_comparison.py
"""
import pandas as pd

from analyze_entry_candidates import HORSES_CSV, _distance_num, _parse_date, load_population

OUT_CSV = "data/processed/rival_comparison.csv"
LOOKBACK_MONTHS = 6


def population_with_trend():
    """모집단 전체에 대해 레이팅추세(직전 출전 대비)를 계산 — 같은 말의 과거 기록만 사용."""
    pop = load_population()
    pop["거리_num"] = pop["거리"].apply(_distance_num)
    pop = pop.dropna(subset=["경주일자_dt", "레이팅_num", "등급"]).sort_values(
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

        my_grade = hist_sorted.iloc[0]["등급"]
        my_distance = _distance_num(hist_sorted.iloc[0]["거리"])
        my_track_raw = hist_sorted.iloc[0]["주로"]
        my_track = str(my_track_raw).split("(")[0] if pd.notna(my_track_raw) else None

        bucket = latest_pop[latest_pop["등급"] == my_grade].copy()
        bucket_label = f"{my_grade}"
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
        bucket["백분위"] = bucket["레이팅_num"].rank(pct=True) * 100
        bucket["추세백분위"] = bucket["레이팅추세"].rank(pct=True, na_option="bottom") * 100
        bucket["조합점수"] = bucket[["백분위", "추세백분위"]].mean(axis=1)
        bucket = bucket.sort_values("조합점수", ascending=False).reset_index(drop=True)
        bucket["상대순위"] = bucket.index + 1
        bucket["비교모집단규모"] = len(bucket)
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
