"""11조 출마등록 분석 결과를 로컬에서 바로 열어보는 반응형 HTML 대시보드로 만든다.

카드형 레이아웃 — 모바일/태블릿/데스크톱에서 자동으로 1~3열로 재배치됨(CSS Grid auto-fill).
서버 없이 파일 더블클릭으로 브라우저에서 열림. daily_update.py가 매일 데이터를 갱신하면
이 스크립트도 같이 돌려서 대시보드를 최신 상태로 유지한다.

사용법:
    python scripts/generate_dashboard.py
    (생성 후 data/dashboard.html 더블클릭해서 열기)
"""
import html as ihtml
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, "scripts")
from analyze_entry_candidates import load_population  # noqa: E402

SCORE_CSV = "data/processed/final_entry_score.csv"
RIVAL_CSV = "data/processed/rival_comparison.csv"
DISTANCE_CSV = "data/processed/distance_breakdown.csv"
INSIGHTS_CSV = "data/processed/horse_insights.csv"
HISTORY_CSV = "data/raw/race_history/race_history_combined.csv"
OUT_HTML = Path("data/dashboard.html")

# dataviz 스킬 참조 팔레트(검증된 기본 팔레트) 카테고리 슬롯1(파랑)/슬롯2(주황) — 인접쌍 CVD 기준 통과
CHART_COLOR_OURS = "#2a78d6"
CHART_COLOR_POP = "#eb6834"
HOME_TRAINER = "손병철"
HOME_LABEL = "11조"


def month_label(ym: str) -> str:
    return f"{int(ym[4:6])}월"


def compute_trainer_trend():
    """손병철 데뷔(2026-07-01) 이후 월별 '손병철 vs 전체 조교사 풀링평균' 승률/복승률."""
    pop = load_population()
    pop["순위_num"] = pd.to_numeric(pop["순위"], errors="coerce")
    pop = pop.dropna(subset=["순위_num"])
    pop["월"] = pop["경주일자"].str[:6]
    debut_month = "202607"
    pop = pop[pop["월"] >= debut_month]

    def agg(g):
        n = len(g)
        return pd.Series({
            "출주": n,
            "승률": round((g["순위_num"] == 1).mean() * 100, 1),
            "복승률": round((g["순위_num"] <= 3).mean() * 100, 1),
        })

    sb = pop[pop["조교사명"] == HOME_TRAINER].groupby("월").apply(agg, include_groups=False)
    allp = pop.groupby("월").apply(agg, include_groups=False)
    months = sorted(set(sb.index) | set(allp.index))
    return months, sb, allp


def build_trend_svg(months, ours_vals, pop_vals, ours_n, pop_n, title) -> str:
    w, h = 520, 190
    pad_l, pad_r, pad_t, pad_b = 34, 100, 14, 26
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b

    all_vals = [v for v in ours_vals + pop_vals if v is not None]
    y_max = max(10, max(all_vals) * 1.15) if all_vals else 10
    y_min = 0

    def x_of(i):
        return pad_l + (i / max(1, len(months) - 1)) * plot_w if len(months) > 1 else pad_l + plot_w / 2

    def y_of(v):
        return pad_t + plot_h - ((v - y_min) / (y_max - y_min)) * plot_h

    def make_line(vals, color, series_label, counts):
        pts = [(i, v) for i, v in enumerate(vals) if v is not None]
        if len(pts) == 0:
            return ""
        path = " ".join(f"{'M' if i == 0 else 'L'}{x_of(xi):.1f},{y_of(v):.1f}" for i, (xi, v) in enumerate(pts))
        line = f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
        dots = ""
        for xi, v in pts:
            n = counts[xi] if counts is not None and counts[xi] is not None else "?"
            tip = f"{series_label} {month_label(months[xi])}: {v:.1f}% ({n}건)"
            dots += (f'<circle class="cdot" cx="{x_of(xi):.1f}" cy="{y_of(v):.1f}" r="7" fill="{color}" '
                     f'fill-opacity="0" stroke="none" tabindex="0" data-tip="{ihtml.escape(tip)}"></circle>'
                     f'<circle cx="{x_of(xi):.1f}" cy="{y_of(v):.1f}" r="4" fill="{color}" pointer-events="none"></circle>')
        return line + dots

    gridlines = ""
    for frac in (0, 0.5, 1.0):
        gy = pad_t + plot_h * (1 - frac)
        gval = y_min + (y_max - y_min) * frac
        gridlines += (f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{w-pad_r}" y2="{gy:.1f}" '
                      f'stroke="var(--chart-grid)" stroke-width="1"/>'
                      f'<text x="{pad_l-6}" y="{gy+3:.1f}" text-anchor="end" font-size="9" '
                      f'fill="var(--chart-muted)">{gval:.0f}%</text>')

    x_labels = "".join(
        f'<text x="{x_of(i):.1f}" y="{h-8}" text-anchor="middle" font-size="10" '
        f'fill="var(--chart-muted)">{month_label(m)}</text>'
        for i, m in enumerate(months)
    )

    ours_line = make_line(ours_vals, CHART_COLOR_OURS, HOME_LABEL, ours_n)
    pop_line = make_line(pop_vals, CHART_COLOR_POP, "전체평균", pop_n)

    # 마지막 유효점 옆에 직접 라벨(범례 대신) — 두 라벨이 겹치지 않게 y좌표를 함께 계산
    def last_point(vals):
        valid = [(i, v) for i, v in enumerate(vals) if v is not None]
        return valid[-1] if valid else None

    ours_last = last_point(ours_vals)
    pop_last = last_point(pop_vals)
    MIN_GAP = 13
    ours_label_y = y_of(ours_last[1]) if ours_last else None
    pop_label_y = y_of(pop_last[1]) if pop_last else None
    if ours_label_y is not None and pop_label_y is not None and abs(ours_label_y - pop_label_y) < MIN_GAP:
        mid = (ours_label_y + pop_label_y) / 2
        if ours_label_y <= pop_label_y:
            ours_label_y, pop_label_y = mid - MIN_GAP / 2, mid + MIN_GAP / 2
        else:
            ours_label_y, pop_label_y = mid + MIN_GAP / 2, mid - MIN_GAP / 2

    def end_label(last, color, text, label_y):
        if last is None:
            return ""
        i, v = last
        x = x_of(i) + 8
        y = max(pad_t + 8, min(h - pad_b - 2, label_y))
        return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="10.5" font-weight="700" fill="{color}">'
                f'{ihtml.escape(text)} {v:.1f}%</text>')

    labels = end_label(ours_last, CHART_COLOR_OURS, HOME_LABEL, (ours_label_y or 0) + 3) + \
        end_label(pop_last, CHART_COLOR_POP, "전체평균", (pop_label_y or 0) + 3)

    return f"""
    <div class="trend-panel">
      <div class="trend-title">{ihtml.escape(title)}</div>
      <svg viewBox="0 0 {w} {h}" class="trend-svg" role="img" aria-label="{ihtml.escape(title)} 추이 그래프">
        {gridlines}
        {pop_line}
        {ours_line}
        {labels}
        {x_labels}
      </svg>
    </div>"""


def render_trend_section() -> str:
    months, sb, allp = compute_trainer_trend()
    if len(months) == 0:
        return ""
    sb_win = [sb.loc[m, "승률"] if m in sb.index else None for m in months]
    sb_place = [sb.loc[m, "복승률"] if m in sb.index else None for m in months]
    sb_n = [int(sb.loc[m, "출주"]) if m in sb.index else None for m in months]
    all_win = [allp.loc[m, "승률"] if m in allp.index else None for m in months]
    all_place = [allp.loc[m, "복승률"] if m in allp.index else None for m in months]
    all_n = [int(allp.loc[m, "출주"]) if m in allp.index else None for m in months]

    win_chart = build_trend_svg(months, sb_win, all_win, sb_n, all_n, "승률 추이 (%)")
    place_chart = build_trend_svg(months, sb_place, all_place, sb_n, all_n, "복승률(3착 이내) 추이 (%)")

    return f"""
  <h2>{HOME_LABEL}({HOME_TRAINER}) 개업 이후 성적 추이 — 전체 조교사 평균과 비교</h2>
  <div class="trend-grid">
    {win_chart}
    {place_chart}
  </div>
  <div class="legend">
    ※ {HOME_TRAINER} 조교사 데뷔일(2026-07-01) 이후 월별 집계. "전체평균"은 그 달 부산경남에서 뛴
    모든 말(방문마 제외)을 통째로 풀링한 승률/복승률 — 트레이너별 평균의 평균이 아니라
    "그 달 아무 말이나 무작위로 골랐을 때" 기준치입니다. 점에 마우스를 올리거나(모바일은 탭) 출주 건수를 확인하세요.
  </div>"""


# ---------------------------------------------------------------- 배지/보조 렌더러

def interval_flag(days) -> str:
    """백테스트로 확인된 적정 출주간격(28~42일) 기준 — 벗어나면 주의 표시."""
    if pd.isna(days):
        return ""
    days = float(days)
    if 28 <= days <= 42:
        return '<span class="badge badge-ok">적정</span>'
    if days < 21 or days > 60:
        return '<span class="badge badge-warn">⚠ 간격주의</span>'
    return '<span class="badge badge-mid">보통</span>'


def interchange_badge(participate, wins) -> str:
    if pd.isna(participate) or int(participate) == 0:
        return ""
    w = int(wins) if pd.notna(wins) else 0
    label = f"{int(participate)}전 {w}승" if w > 0 else f"{int(participate)}전"
    cls = "badge-ic-win" if w > 0 else "badge-ic"
    return f'<span class="badge {cls}">교류 {label}</span>'


def optimal_distance_badge(insight) -> str:
    if insight is None or pd.isna(insight.get("최적거리")):
        return ""
    dist = int(insight["최적거리"])
    pct = insight.get("최적거리백분위")
    pct_txt = f" ({pct:.0f}%ile)" if pd.notna(pct) else ""
    thin = "1개뿐" in str(insight.get("최적거리근거", ""))
    cls = "badge-mid" if thin else "badge-ok"
    title = ihtml.escape(str(insight.get("최적거리근거", "")))
    return f'<span class="badge {cls}" title="{title}">최적거리 {dist}M{pct_txt}</span>'


def versatility_badge(insight) -> str:
    if insight is None or not bool(insight.get("양면형")):
        return ""
    f, c = int(insight.get("선행성공횟수", 0)), int(insight.get("추입성공횟수", 0))
    return f'<span class="badge badge-ic">양면형(선행{f}·추입{c})</span>'


def prior_trainer_badge(insight) -> str:
    if insight is None or pd.isna(insight.get("이전소속조교사")):
        return ""
    prev = ihtml.escape(str(insight["이전소속조교사"]))
    date_raw = str(insight.get("이전소속최근경주일", ""))
    date_txt = f"{date_raw[:4]}.{date_raw[4:6]}" if len(date_raw) >= 6 else ""
    title = f"손병철 데뷔(2026-07-01) 이전, {date_txt}까지 {prev} 마방 소속이었음"
    return f'<span class="badge badge-mid" title="{ihtml.escape(title)}">이전: {prev}({date_txt})</span>'


def attention_box(insight) -> str:
    if insight is None:
        return ""
    flags = insight.get("신경써야할점")
    if pd.isna(flags) or not flags:
        return ""
    return f'<div class="attention">⚠ {ihtml.escape(str(flags))}</div>'


def score_color(score: float) -> str:
    if pd.isna(score):
        return "#888"
    if score >= 65:
        return "var(--good)"
    if score >= 50:
        return "var(--warn)"
    return "var(--bad)"


def stat(label: str, value: str) -> str:
    return f'<div class="stat"><div class="stat-label">{label}</div><div class="stat-value">{value}</div></div>'


# ---------------------------------------------------------------- 상세 표(펼치기 안)

def render_rival_table(rivals: pd.DataFrame) -> str:
    rows = []
    for _, r in rivals.iterrows():
        is_mine = bool(r["우리말여부"])
        unranked = pd.isna(r["상대순위"])
        classes = " ".join(c for c in ["is-mine" if is_mine else "", "is-unranked" if unranked else ""] if c)
        cls = f' class="{classes}"' if classes else ""
        mark = " ★" if is_mine else ""
        rank_cell = "–" if unranked else int(r["상대순위"])
        rows.append(f"""
        <tr{cls}>
          <td>{rank_cell}</td>
          <td>{ihtml.escape(str(r['마명']))}{mark}</td>
          <td>{ihtml.escape(str(r['조교사명']))}</td>
          <td>{ihtml.escape(str(r['마주명']))}</td>
          <td>{'' if pd.isna(r['레이팅_num']) else f"{r['레이팅_num']:.0f}"}</td>
          <td>{'' if pd.isna(r['레이팅추세']) else f"{r['레이팅추세']:+.0f}"}</td>
          <td>{'' if pd.isna(r['조합점수']) else f"{r['조합점수']:.1f}"}</td>
        </tr>""")
    return "".join(rows)


def render_distance_table(rows_df: pd.DataFrame) -> str:
    out = []
    for _, r in rows_df.iterrows():
        pct = r["등급내백분위"]
        pct_cell = "" if pd.isna(pct) else f'<span style="color:{score_color(pct)};font-weight:700;">{pct:.0f}%</span>'
        out.append(f"""
        <tr>
          <td>{int(r['거리'])}M</td>
          <td>{int(r['출전횟수'])}전</td>
          <td>{'' if pd.isna(r['평균순위비율']) else f"{r['평균순위비율']:.2f}"}</td>
          <td>{'' if pd.isna(r['최고순위']) else f"{int(r['최고순위'])}위"}</td>
          <td>{ihtml.escape(str(r['등급'])) if pd.notna(r['등급']) else ''}</td>
          <td>{'' if pd.isna(r['최근레이팅']) else f"{r['최근레이팅']:.0f}"}</td>
          <td>{pct_cell}</td>
          <td>{ihtml.escape(str(r['최근출전일']))}</td>
        </tr>""")
    return "".join(out)


def build_detail_blocks(hr_name: str, rivals: pd.DataFrame, distances: pd.DataFrame) -> str:
    rival_block = ""
    if not rivals.empty:
        sub = rivals[rivals["기준말_마명"] == hr_name]
        if len(sub) > 0:
            bucket_label = ihtml.escape(str(sub.iloc[0]["비교기준"]))
            pop_size = int(sub.iloc[0]["비교모집단규모"])
            my_row = sub[sub["우리말여부"]]
            my_rank = (int(my_row.iloc[0]["상대순위"])
                       if len(my_row) > 0 and pd.notna(my_row.iloc[0]["상대순위"]) else None)
            all_rivals = sub.sort_values("상대순위", na_position="last")
            rank_text = f" — 모집단 {pop_size}두 중 {my_rank}위" if my_rank else (
                " — 레이팅 없어 순위 비교 불가" if len(my_row) > 0 else "")
            rival_block = f"""
            <details>
              <summary>상대마 비교 ({ihtml.escape(bucket_label)}{rank_text}, 전체 {len(all_rivals)}두)</summary>
              <div class="scroll-box">
              <table class="mini-table">
                <thead><tr><th>순위</th><th>마명</th><th>조교사</th><th>마주</th><th>레이팅</th><th>추세</th><th>조합점수</th></tr></thead>
                <tbody>{render_rival_table(all_rivals)}</tbody>
              </table>
              </div>
            </details>"""

    distance_block = ""
    if not distances.empty:
        d_sub = distances[distances["마명"] == hr_name].sort_values("거리")
        if len(d_sub) > 0:
            distance_block = f"""
            <details>
              <summary>거리별 성적 ({len(d_sub)}개 거리x등급 조합)</summary>
              <div class="scroll-box">
              <table class="mini-table">
                <thead><tr><th>거리</th><th>출전</th><th>평균순위비율</th><th>최고순위</th><th>등급</th><th>레이팅</th><th>백분위</th><th>최근출전일</th></tr></thead>
                <tbody>{render_distance_table(d_sub)}</tbody>
              </table>
              </div>
            </details>"""

    return distance_block + rival_block


# ---------------------------------------------------------------- 카드

def render_scored_card(rank: int, r: pd.Series, insight, rivals: pd.DataFrame, distances: pd.DataFrame) -> str:
    color = score_color(r["최종점수"])
    hr_name = ihtml.escape(str(r["마명"]))
    detail_blocks = build_detail_blocks(r["마명"], rivals, distances)

    chips = "".join(filter(None, [
        f'<span class="chip">{ihtml.escape(str(r["최근출전등급"]))}'
        f'{"" if pd.isna(r["최근출전거리"]) else f" · {int(r['최근출전거리'])}M"}</span>',
        optimal_distance_badge(insight),
        versatility_badge(insight),
        interval_flag(r["경과일"]),
        interchange_badge(r.get("교류경주참가"), r.get("교류경주우승")),
        prior_trainer_badge(insight),
    ]))

    stats = "".join([
        stat("등급내백분위", "" if pd.isna(r["등급내백분위"]) else f"{r['등급내백분위']:.0f}%"),
        stat("레이팅추세", ihtml.escape(str(r["추세"]))),
        stat("선행성향", "" if pd.isna(r["선행성향"]) else f"{r['선행성향']*100:.0f}%"),
        stat("추입성향", "" if pd.isna(r["추입성향"]) else f"{r['추입성향']*100:+.0f}%"),
    ])

    days_text = "" if pd.isna(r["경과일"]) else f"최근출전 {int(r['경과일'])}일 전"

    return f"""
    <div class="card">
      <div class="card-top">
        <div class="rank">{rank}</div>
        <div class="card-title">
          <div class="hname">{hr_name}</div>
          <div class="sub">{days_text}</div>
          {attention_box(insight)}
        </div>
        <div class="score-pill" style="background:{color}">{r['최종점수']:.1f}</div>
      </div>
      <div class="chip-row">{chips}</div>
      <div class="stat-grid">{stats}</div>
      {f'<div class="details">{detail_blocks}</div>' if detail_blocks else ''}
    </div>"""


def render_unscored_card(r: pd.Series, insight, rivals: pd.DataFrame, distances: pd.DataFrame) -> str:
    reason = "레이팅 없음(신마)" if pd.isna(r["최근레이팅"]) else "레이팅추세 계산불가(경주이력 부족)"
    hr_name = ihtml.escape(str(r["마명"]))
    detail_blocks = build_detail_blocks(r["마명"], rivals, distances)

    chips = "".join(filter(None, [
        f'<span class="chip">{ihtml.escape(str(r["소속마목록등급"]))}</span>',
        optimal_distance_badge(insight),
        versatility_badge(insight),
        interval_flag(r["경과일"]),
        interchange_badge(r.get("교류경주참가"), r.get("교류경주우승")),
        prior_trainer_badge(insight),
    ]))

    stats = "".join([
        stat("레이팅", "" if pd.isna(r.get("최근레이팅")) else f"{r['최근레이팅']:.0f}"),
        stat("최근출전등급", ihtml.escape(str(r["최근출전등급"])) if pd.notna(r.get("최근출전등급")) else "-"),
        stat("선행성향", "" if pd.isna(r.get("선행성향")) else f"{r['선행성향']*100:.0f}%"),
        stat("추입성향", "" if pd.isna(r.get("추입성향")) else f"{r['추입성향']*100:+.0f}%"),
    ])

    days_text = "" if pd.isna(r["경과일"]) else f"최근출전 {int(r['경과일'])}일 전"

    return f"""
    <div class="card card-muted">
      <div class="card-top">
        <div class="card-title">
          <div class="hname">{hr_name}</div>
          <div class="sub">{days_text} · <span class="reason">{reason}</span></div>
          {attention_box(insight)}
        </div>
      </div>
      <div class="chip-row">{chips}</div>
      <div class="stat-grid">{stats}</div>
      {f'<div class="details">{detail_blocks}</div>' if detail_blocks else ''}
    </div>"""


def main():
    scores = pd.read_csv(SCORE_CSV)
    rivals = pd.read_csv(RIVAL_CSV) if Path(RIVAL_CSV).exists() else pd.DataFrame()
    distances = pd.read_csv(DISTANCE_CSV) if Path(DISTANCE_CSV).exists() else pd.DataFrame()
    insights = pd.read_csv(INSIGHTS_CSV) if Path(INSIGHTS_CSV).exists() else pd.DataFrame()
    insights_by_name = {r["마명"]: r for _, r in insights.iterrows()} if not insights.empty else {}

    scored = scores.dropna(subset=["최종점수"]).sort_values("최종점수", ascending=False)
    unscored = scores[scores["최종점수"].isna()].sort_values("경과일", na_position="last")

    scored_cards = "".join(
        render_scored_card(i, r, insights_by_name.get(r["마명"]), rivals, distances)
        for i, (_, r) in enumerate(scored.iterrows(), 1)
    )
    unscored_cards = "".join(
        render_unscored_card(r, insights_by_name.get(r["마명"]), rivals, distances)
        for _, r in unscored.iterrows()
    )

    trend_section = render_trend_section()

    html = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>11조 대시보드</title>
<style>
  :root {{
    --bg: #f6f8fa; --surface: #fff; --ink: #1f2328; --ink-muted: #656d76;
    --border: #e5e9ee; --chip-bg: #eef0f2; --chip-ink: #444;
    --good: #1a7f37; --good-bg: #d4f4dd; --warn: #9a6700; --warn-bg: #fff0e8;
    --bad: #cf222e; --accent-bg: #eef0ff; --accent-ink: #3451b2;
    --accent2-bg: #fff4d6; --accent2-ink: #9a6700;
    --chart-grid: #e1e0d9; --chart-muted: #898781;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0d1117; --surface: #161b22; --ink: #e6edf3; --ink-muted: #8b949e;
      --border: #30363d; --chip-bg: #21262d; --chip-ink: #c9d1d9;
      --good: #3fb950; --good-bg: #0f2c1a; --warn: #d29922; --warn-bg: #2d2109;
      --bad: #f85149; --accent-bg: #15213a; --accent-ink: #79a6ff;
      --accent2-bg: #2d2410; --accent2-ink: #e3b341;
      --chart-grid: #2c2c2a; --chart-muted: #898781;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", Malgun Gothic, sans-serif; background:var(--bg); color:var(--ink); margin:0; padding:20px; }}
  .wrap {{ max-width: 1240px; margin: 0 auto; }}
  h1 {{ font-size: 19px; margin: 0 0 4px; }}
  h2 {{ font-size: 15px; margin: 32px 0 12px; color:var(--ink-muted); }}
  .meta {{ color:var(--ink-muted); font-size: 12.5px; margin-bottom: 18px; line-height:1.6; }}
  .legend {{ font-size: 12px; color: var(--ink-muted); margin-top: 16px; line-height: 2; }}

  .cards-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 14px; }}

  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }}
  .card-muted {{ opacity: 0.88; }}
  .card-top {{ display: flex; align-items: flex-start; gap: 10px; }}
  .rank {{ flex: 0 0 auto; width: 26px; height: 26px; border-radius: 50%; background: var(--chip-bg); color: var(--chip-ink);
           display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; }}
  .card-title {{ flex: 1 1 auto; min-width: 0; }}
  .hname {{ font-weight: 800; font-size: 19px; color: var(--ink); letter-spacing: -0.2px; }}
  .sub {{ font-size: 11.5px; color: var(--ink-muted); margin-top: 1px; }}
  .reason {{ color: var(--ink-muted); }}
  .attention {{ color: var(--warn); font-size: 11.5px; font-weight: 600; margin-top: 4px; }}
  .score-pill {{ flex: 0 0 auto; color: #fff; font-weight: 800; font-size: 15px; padding: 5px 11px; border-radius: 8px; }}

  .chip-row {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }}
  .chip {{ background: var(--chip-bg); color: var(--chip-ink); font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 10px; }}
  .badge {{ display: inline-block; padding: 3px 8px; border-radius: 10px; font-size: 11px; font-weight: 700; white-space: nowrap; }}
  .badge-ok {{ background: var(--good-bg); color: var(--good); }}
  .badge-mid {{ background: var(--chip-bg); color: var(--ink-muted); }}
  .badge-warn {{ background: var(--warn-bg); color: var(--warn); }}
  .badge-ic {{ background: var(--accent-bg); color: var(--accent-ink); }}
  .badge-ic-win {{ background: var(--accent2-bg); color: var(--accent2-ink); }}

  .stat-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 12px; }}
  .stat {{ background: var(--bg); border-radius: 6px; padding: 7px 4px; text-align: center; }}
  .stat-label {{ font-size: 10px; color: var(--ink-muted); margin-bottom: 2px; }}
  .stat-value {{ font-size: 13px; font-weight: 700; }}
  @media (max-width: 420px) {{ .stat-grid {{ grid-template-columns: repeat(2, 1fr); }} }}

  .details {{ margin-top: 10px; border-top: 1px solid var(--border); padding-top: 8px; }}
  details {{ margin-top: 4px; }}
  summary {{ cursor: pointer; color: var(--accent-ink); font-size: 12.5px; font-weight: 600; }}
  .scroll-box {{ max-height: 380px; overflow-y: auto; overflow-x: auto; margin-top: 8px; border: 1px solid var(--border); border-radius: 6px; -webkit-overflow-scrolling: touch; }}
  .mini-table {{ width: 100%; min-width: 480px; border-collapse: collapse; }}
  .mini-table th {{ position: sticky; top: 0; background: var(--chip-bg); z-index: 1; }}
  .mini-table th, .mini-table td {{ font-size: 11.5px; padding: 5px 8px; text-align: center; border-bottom: 1px solid var(--border); white-space: nowrap; }}
  .mini-table tr.is-mine {{ background: var(--accent-bg); font-weight: 700; }}
  .mini-table tr.is-unranked {{ color: var(--ink-muted); }}
  .mini-table tr.is-unranked.is-mine {{ background: var(--chip-bg); }}

  .guide {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
            padding: 16px 18px; margin-bottom: 18px; }}
  .guide summary {{ font-size: 15px; font-weight: 700; color: var(--ink); list-style: none; cursor: pointer; }}
  .guide summary::-webkit-details-marker {{ display: none; }}
  .guide summary::before {{ content: "▸ "; color: var(--accent-ink); }}
  .guide[open] summary::before {{ content: "▾ "; }}
  .guide-body {{ margin-top: 14px; font-size: 13px; line-height: 1.75; color: var(--ink); }}
  .guide-body h3 {{ font-size: 13.5px; margin: 16px 0 6px; color: var(--ink); }}
  .guide-body h3:first-child {{ margin-top: 0; }}
  .guide-body ul {{ margin: 4px 0; padding-left: 20px; }}
  .guide-body li {{ margin: 3px 0; }}
  .guide-note {{ margin-top: 14px; padding: 10px 12px; background: var(--warn-bg); color: var(--warn);
                 border-radius: 8px; font-size: 12.5px; line-height: 1.6; }}

  .trend-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; }}
  .trend-panel {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px 4px; }}
  .trend-title {{ font-size: 12.5px; font-weight: 700; color: var(--ink); margin-bottom: 4px; }}
  .trend-svg {{ width: 100%; height: auto; display: block; }}
  .cdot {{ cursor: pointer; }}
  .chart-tip {{ position: fixed; z-index: 50; background: var(--ink); color: var(--surface);
                font-size: 11.5px; font-weight: 600; padding: 5px 9px; border-radius: 6px;
                pointer-events: none; white-space: nowrap; transform: translate(-50%, -100%);
                margin-top: -8px; display: none; }}
  .chart-tip.show {{ display: block; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>11조 대시보드</h1>
  <div class="meta">
    생성 시각: {datetime.now():%Y-%m-%d %H:%M}<br>
    레이팅(백분위+추세) + 러닝스타일(선행+추입) 조합점수, 동등가중 · 백테스트 검증 완료
    (Spearman -0.3149, 경주단위 1위픽 승률 2.11배 — 단 6~8두 소규모 경주는 표본 부족으로 추가 검증 필요)
  </div>

  <details class="guide" open>
    <summary>이 화면은 무엇이고, 어떻게 보는 건가요? (처음이면 읽어보세요)</summary>
    <div class="guide-body">
      <h3>무엇을 하는 화면인가요?</h3>
      <p>11조(손병철 조교사) 소속마들을 <b>데이터로 분석해서 지금 어떤 말 상태가 좋은지</b> 보여주는 도구입니다.
      감이 아니라 과거 1년치 실제 경주 결과를 통계적으로 검증한 방식을 씁니다. 매일 자동으로 최신 데이터로 갱신됩니다.</p>

      <h3>최종점수는 어떻게 나온 건가요?</h3>
      <p>아래 4가지를 동일한 비중으로 합쳐서 계산합니다 (점수가 높을수록 "지금 상태가 좋다"는 뜻 — 100점 만점이 아니라 상대적 순위입니다):</p>
      <ul>
        <li><b>등급내백분위</b> — 이 말의 레이팅이, 같은 등급·거리·주로상태에서 뛴 다른 마방 말들과 비교해 상위 몇 %인지</li>
        <li><b>레이팅추세</b> — 직전 경주보다 가장 최근 경주 레이팅이 올랐는지(+)/내렸는지(-)</li>
        <li><b>선행성향</b> — 경주 초반에 앞서 나가는 경향 (%가 높을수록 선행형)</li>
        <li><b>추입성향</b> — 경주 후반에 순위를 끌어올리는 경향 (양수면 추입/뒷심형)</li>
      </ul>

      <h3>이거 믿을 만한가요?</h3>
      <p>과거 1년치(710개 경주, 7,800여 출전기록)로 검증했습니다. <b>이 점수로 1등을 뽑았을 때, 무작위로 찍었을 때보다 약 2배 더 자주 실제로 우승</b>했습니다
      (367개 경주 테스트, 승률 22.1% vs 무작위 10.5%). 다만 6~8두짜리 소규모 경주는 아직 표본이 적어 추가 검증이 필요합니다.</p>

      <h3>배지는 무슨 뜻인가요?</h3>
      <ul>
        <li><span class="badge badge-ok">적정</span> 출주간격이 딱 좋은 시기(28~42일, 과거 데이터로 확인된 최적 구간)</li>
        <li><span class="badge badge-warn">⚠ 간격주의</span> 너무 급하게(21일 미만) 또는 너무 오래 쉬고(60일 초과) 나가는 경우</li>
        <li><b>최적거리 배지</b> — 이 말이 지금 등급에서 가장 성적이 좋았던 거리 (비교 가능한 거리가 1개뿐이면 "판단 보류 권장"이라고 표시됨)</li>
        <li><span class="badge badge-ic">양면형</span> — 선행으로도, 추입으로도 둘 다 3착 이내 성공한 적 있는 말</li>
        <li><span class="badge badge-ic-win">교류 N전 M승</span> — 서울/제주/영천 등 원정 경주 전적 (참고용, 점수엔 미반영)</li>
        <li><span class="badge badge-mid">이전: 조교사명(날짜)</span> — 손병철 조교사 데뷔(2026-07-01) 이전 마지막으로 소속됐던 조교사. 대부분 "임금만"으로 나오는 건 데뷔 당시 마방을 인수받은 흔적(정상)</li>
      </ul>

      <h3>카드를 펼치면 뭐가 나오나요?</h3>
      <p>각 말 카드 아래 <b>"거리별 성적"</b>을 펼치면 이 말이 뛰어본 모든 거리·등급에서의 성적을,
      <b>"상대마 비교"</b>를 펼치면 같은 등급·거리·주로상태 조건의 다른 마방 말들과 나란히 순위를 비교해서 볼 수 있습니다
      (★ 표시 = 우리 말). 레이팅이 없는 말(신마·최하위군)도 같은 조건의 상대마 목록 맨 아래에 순위 없이("–") 같이 표시됩니다
      — 순위는 못 매기지만 어떤 말들과 같이 뛰는지는 보이게 하기 위함입니다.
      OPEN 경주는 등급이 아니라 "등급 제한 없이 뛰는 경주"라 레이팅이 경주마다 들쭉날쭉이라서,
      OPEN에서 뛴 말은 실제 레이팅 값으로 번호등급(1~6등급)에 맞춰 환산해서 비교군을 묶습니다
      (비교 요약에 "국3등급(OPEN환산, 원등급 국OPEN)"처럼 표시됨).</p>

      <div class="guide-note">
        ⚠ <b>이 점수는 참고자료입니다.</b> 실제 출마등록(경주 신청)은 조교사가 직접 판단해서 하는 것이고,
        컨디션·부상 여부처럼 데이터에 안 잡히는 부분은 이 도구가 알 수 없습니다. 레이팅이 아직 없는 신마는
        점수가 안 나와서 맨 아래 별도 표에 나옵니다.
      </div>
    </div>
  </details>
{trend_section}
  <div class="cards-grid">
    {scored_cards}
  </div>

  <div class="legend">
    ※ 카드를 펼치면(상세보기) 같은 등급·거리·주로상태 모집단 전체(타 마방 포함) 대비 순위, 거리별 성적을 볼 수 있습니다. ★ = 우리 말<br>
    ※ 간격 배지 — <span class="badge badge-ok">적정</span> 28~42일(백테스트 최적구간) /
    <span class="badge badge-mid">보통</span> 그 외 /
    <span class="badge badge-warn">⚠ 간격주의</span> 21일 미만 또는 60일 초과<br>
    ※ <span class="badge badge-ic">양면형</span> 배지 — 과거 경주에서 선행·추입 둘 다로 3착 이내 성공 이력 있음<br>
    ※ <span class="badge badge-ic">교류</span> 배지 — 서울/제주/영천 등 타 경마장 원정 출전·우승 이력 (숫자 점수엔 미반영, 참고용)<br>
    ※ 주의문구(⚠)는 레이팅 하락세·출주간격 부적정·현재등급 하위권·러닝스타일 표본부족을 자동 집계한 것입니다.
  </div>

  <h2>신마·미검마 ({len(unscored)}두, 레이팅/추세 데이터 부족으로 점수 미산출)</h2>
  <div class="cards-grid">
    {unscored_cards}
  </div>
</div>
<div class="chart-tip" id="chart-tip"></div>
<script>
(function() {{
  var tip = document.getElementById('chart-tip');
  function showTip(el, x, y) {{
    tip.textContent = el.getAttribute('data-tip');
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
    tip.classList.add('show');
  }}
  function hideTip() {{ tip.classList.remove('show'); }}
  document.addEventListener('mouseover', function(e) {{
    var el = e.target.closest('.cdot');
    if (el) showTip(el, e.clientX, e.clientY);
  }});
  document.addEventListener('mousemove', function(e) {{
    if (tip.classList.contains('show') && e.target.closest('.cdot')) {{
      tip.style.left = e.clientX + 'px';
      tip.style.top = e.clientY + 'px';
    }}
  }});
  document.addEventListener('mouseout', function(e) {{
    if (e.target.closest('.cdot')) hideTip();
  }});
  document.addEventListener('touchstart', function(e) {{
    var el = e.target.closest('.cdot');
    if (el) {{
      var t = e.touches[0];
      showTip(el, t.clientX, t.clientY);
      e.preventDefault();
    }} else {{
      hideTip();
    }}
  }}, {{passive: false}});
  document.addEventListener('touchend', function() {{ setTimeout(hideTip, 1500); }});
}})();
</script>
</body>
</html>"""

    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"대시보드 생성 완료 -> {OUT_HTML.resolve()}")


if __name__ == "__main__":
    main()
