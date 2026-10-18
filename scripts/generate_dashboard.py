"""11조 출마등록 분석 결과를 로컬에서 바로 열어보는 반응형 HTML 대시보드로 만든다.

카드형 레이아웃 — 모바일/태블릿/데스크톱에서 자동으로 1~3열로 재배치됨(CSS Grid auto-fill).
서버 없이 파일 더블클릭으로 브라우저에서 열림. daily_update.py가 매일 데이터를 갱신하면
이 스크립트도 같이 돌려서 대시보드를 최신 상태로 유지한다.

사용법:
    python scripts/generate_dashboard.py
    (생성 후 data/dashboard.html 더블클릭해서 열기)
"""
import html as ihtml
from datetime import datetime
from pathlib import Path

import pandas as pd

SCORE_CSV = "data/processed/final_entry_score.csv"
RIVAL_CSV = "data/processed/rival_comparison.csv"
DISTANCE_CSV = "data/processed/distance_breakdown.csv"
INSIGHTS_CSV = "data/processed/horse_insights.csv"
OUT_HTML = Path("data/dashboard.html")


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
        cls = ' class="is-mine"' if is_mine else ""
        mark = " ★" if is_mine else ""
        rows.append(f"""
        <tr{cls}>
          <td>{int(r['상대순위'])}</td>
          <td>{ihtml.escape(str(r['마명']))}{mark}</td>
          <td>{ihtml.escape(str(r['조교사명']))}</td>
          <td>{ihtml.escape(str(r['마주명']))}</td>
          <td>{r['레이팅_num']:.0f}</td>
          <td>{'' if pd.isna(r['레이팅추세']) else f"{r['레이팅추세']:+.0f}"}</td>
          <td>{r['조합점수']:.1f}</td>
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
            my_rank = int(sub[sub["우리말여부"]].iloc[0]["상대순위"]) if sub["우리말여부"].any() else None
            all_rivals = sub.sort_values("상대순위")
            rank_text = f" — 모집단 {pop_size}두 중 {my_rank}위" if my_rank else ""
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


def render_unscored_card(r: pd.Series, insight, distances: pd.DataFrame) -> str:
    reason = "레이팅 없음(신마)" if pd.isna(r["최근레이팅"]) else "레이팅추세 계산불가(경주이력 부족)"
    hr_name = ihtml.escape(str(r["마명"]))
    detail_blocks = build_detail_blocks(r["마명"], pd.DataFrame(), distances)

    chips = "".join(filter(None, [
        f'<span class="chip">{ihtml.escape(str(r["소속마목록등급"]))}</span>',
        optimal_distance_badge(insight),
        versatility_badge(insight),
        interval_flag(r["경과일"]),
        interchange_badge(r.get("교류경주참가"), r.get("교류경주우승")),
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
        render_unscored_card(r, insights_by_name.get(r["마명"]), distances)
        for _, r in unscored.iterrows()
    )

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
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0d1117; --surface: #161b22; --ink: #e6edf3; --ink-muted: #8b949e;
      --border: #30363d; --chip-bg: #21262d; --chip-ink: #c9d1d9;
      --good: #3fb950; --good-bg: #0f2c1a; --warn: #d29922; --warn-bg: #2d2109;
      --bad: #f85149; --accent-bg: #15213a; --accent-ink: #79a6ff;
      --accent2-bg: #2d2410; --accent2-ink: #e3b341;
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
  .hname {{ font-weight: 700; font-size: 15px; }}
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
</style>
</head>
<body>
<div class="wrap">
  <h1>11조 대시보드</h1>
  <div class="meta">
    생성 시각: {datetime.now():%Y-%m-%d %H:%M}<br>
    레이팅(백분위+추세) + 러닝스타일(선행+추입) 조합점수, 동등가중 · 백테스트 검증 완료
    (Spearman -0.3175, 경주단위 1위픽 승률 2.03배 — 단 6~8두 소규모 경주는 표본 부족으로 추가 검증 필요)
  </div>

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
</body>
</html>"""

    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"대시보드 생성 완료 -> {OUT_HTML.resolve()}")


if __name__ == "__main__":
    main()
