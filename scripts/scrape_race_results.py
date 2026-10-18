"""부산경남(meet=3) 전체 경주 결과를 경주일자 단위로 수집한다 (race.kra.co.kr).

이게 "같은 등급 다른 마방 말들과 비교" 분석의 기반 데이터다 — 레이스 1건을 조회하면
그 경주에 나온 전체 출전마(마번/마명/산지/성별/연령/중량/레이팅/기수/조교사/마주/도착차/
마체중/배당)와 경주 메타정보(등급/거리/주로상태/함수율/날씨/상금구조)가 한 번에 나온다.

증분 수집 설계: data/processed/race_results_state.json에 "이미 수집한 가장 오래된/최신 날짜"를
기록해서, 다음 실행부터는 새로 열린 경주만 추가로 가져온다. 처음 한 번만 과거분을 백필하면
그 다음부터는 빠르다.

사용법:
    # 최초 백필 (예: 과거 12개월)
    python scripts/scrape_race_results.py --months 12

    # 이후 증분 수집 (상태 파일 기준 이어서)
    python scripts/scrape_race_results.py --incremental
"""
import argparse
import csv
import html as ihtml
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

BASE = "https://race.kra.co.kr/raceScore"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
STATE_PATH = Path("data/processed/race_results_state.json")
OUT_DIR = Path("data/raw/race_results")

SECTIONAL_POINTS = ["S1F", "G8F", "G6F", "G4F", "G3F", "G2F", "G1F"]  # 구간별 통과순위 체크포인트
SECTIONAL_TIME_LABELS = ["T_S_1F", "T_10_8F", "T_8_6F", "T_6_4F", "T_4_2F", "T_2F_G", "T_3F_G", "T_1F_G"]

FIELD_COLUMNS = [
    "순위", "마번", "마명", "마호_hrNo", "산지", "성별", "연령", "중량", "레이팅",
    "기수명", "조교사명", "마주명", "도착차", "마체중", "마체중증감", "단승", "연승", "장구현황",
    "경주기록", *SECTIONAL_POINTS, *SECTIONAL_TIME_LABELS,
]
META_COLUMNS = [
    "경주일자", "경주번호", "경기장", "날씨", "주로상태", "함수율", "출발시간",
    "등급", "거리", "부담종류", "경주명", "레이팅조건", "연령조건",
]


def _clean(txt: str) -> str:
    txt = re.sub(r"<[^>]+>", "", txt)
    return ihtml.unescape(txt).strip()


def _post(path: str, data: dict) -> str:
    resp = requests.post(f"{BASE}/{path}", data=data, headers=HEADERS, timeout=30)
    resp.encoding = "euc-kr"
    return resp.text


def list_race_dates(meet: str, page_index: int) -> list[str]:
    """ScoretableScoreList.do 한 페이지(약 10개 날짜, meet 혼합)에서 지정 meet 날짜만 추출."""
    content = _post("ScoretableScoreList.do", {
        "meet": meet, "pageIndex": str(page_index), "nextFlag": "false", "Act": "04", "Sub": "1",
    })
    pairs = re.findall(r"ScoreDailyPopup\('(\d+)','(\d+)'\)", content)
    return [d for m, d in pairs if m == meet]


def list_races_for_date(meet: str, rc_date: str) -> list[str]:
    """그날 열린 경주번호 목록."""
    content = _post("ScoretableDailyList.do", {
        "meet": meet, "realRcDate": rc_date, "Act": "04", "Sub": "1",
    })
    nos = re.findall(r"ScoreDetailPopup\('\d+','\d+','(\d+)'\)", content)
    return sorted(set(nos), key=int)


def fetch_race_detail(meet: str, rc_date: str, rc_no: str) -> tuple[dict, list[dict]]:
    """경주 1건의 메타정보 + 전체 출전마 결과."""
    content = _post("ScoretableDetailList.do", {
        "meet": meet, "realRcDate": rc_date, "realRcNo": rc_no, "Act": "04", "Sub": "1",
    })

    meta = {"경주일자": rc_date, "경주번호": rc_no}
    head_m = re.search(
        r'colspan="4">([^<]+)</td>\s*<td class="bgnone">([^<]*)</td>\s*'
        r'<td class="bgnone">([^<]*)</td>\s*<td class="bgnone">([^<]*)</td>\s*'
        r'<td class="bgnone">([^<]*)</td>\s*<td class="bgnone">([^<]*)</td>',
        content,
    )
    if head_m:
        title, _, weather, track, moisture, start_time = head_m.groups()
        meta["경기장"] = _clean(title)
        meta["날씨"] = _clean(weather)
        meta["주로상태"] = _clean(track)
        meta["함수율"] = _clean(moisture)
        meta["출발시간"] = _clean(start_time)

    cond_m = re.search(
        r"<tr class=\"alignC\">\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>\s*"
        r"<td>\s*(?:.*?<span[^>]*>([^<]*)</span>.*?|([^<]*))</td>\s*"
        r"<td colspan=\"2\">([^<]*)</td>\s*<td colspan=\"2\">([^<]*)</td>",
        content, re.S,
    )
    if cond_m:
        grade, distance, weight_type, race_name_a, race_name_b, rating_cond, age_cond = cond_m.groups()
        meta["등급"] = _clean(grade)
        meta["거리"] = _clean(distance)
        meta["부담종류"] = _clean(weight_type)
        meta["경주명"] = _clean(race_name_a or race_name_b or "")
        meta["레이팅조건"] = _clean(rating_cond)
        meta["연령조건"] = _clean(age_cond)

    tbodies = re.findall(r"<tbody>(.*?)</tbody>", content, re.S)
    field = []
    if tbodies:
        tbody = tbodies[0]  # 경주상세성적(출전마) 테이블은 항상 문서상 첫 번째 tbody
        for tr in re.findall(r"<tr>(.*?)</tr>", tbody, re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if len(tds) < 15:
                continue
            rank = _clean(tds[0])
            post_no = _clean(tds[1])
            horse_cell = tds[2]
            hr_m = re.search(r"goHorse\('(\d+)'", horse_cell)
            hr_no = hr_m.group(1) if hr_m else ""
            hr_name = _clean(horse_cell)
            origin = _clean(tds[3])
            sex = _clean(tds[4])
            age = _clean(tds[5])
            weight = _clean(tds[6])
            rating = _clean(tds[7])
            jockey = _clean(tds[8])
            trainer = _clean(tds[9])
            owner = _clean(tds[10])
            margin = _clean(tds[11])
            bw_raw = _clean(tds[12])
            bw_m = re.match(r"(\d+)\(([+-]?\d+)\)", bw_raw)
            bw, bw_delta = bw_m.groups() if bw_m else (bw_raw, "")
            win_odds = _clean(tds[13]) if len(tds) > 13 else ""
            place_odds = _clean(tds[14]) if len(tds) > 14 else ""
            equip = _clean(tds[15]) if len(tds) > 15 else ""
            field.append({
                "순위": rank, "마번": post_no, "마명": hr_name, "마호_hrNo": hr_no,
                "산지": origin, "성별": sex, "연령": age, "중량": weight, "레이팅": rating,
                "기수명": jockey, "조교사명": trainer, "마주명": owner, "도착차": margin,
                "마체중": bw, "마체중증감": bw_delta, "단승": win_odds, "연승": place_odds,
                "장구현황": equip,
            })

    sectional_by_post = parse_sectional_table(tbodies[1]) if len(tbodies) > 1 else {}
    for row in field:
        row.update(sectional_by_post.get(row["마번"], {}))

    return meta, field


def parse_sectional_table(tbody: str) -> dict:
    """'구간별통과순위/구간별통과기록' 테이블 — 선행/추입 분석의 기반 데이터.
    구간별통과순위 셀은 "2- - - 2- 1- 1- 1"처럼 하이픈+공백으로 구분된 순위 시퀀스
    (S1F,G8F,G6F,G4F,G3F,G2F,G1F 7개 체크포인트). 해당 거리에서 측정 안 된 구간은 빈값("-")."""
    result = {}
    for tr in re.findall(r"<tr>(.*?)</tr>", tbody, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 12:
            continue
        post_no = _clean(tds[1])
        seq_raw = re.sub(r"\s+", " ", _clean(tds[2])).strip()
        ranks = [tok.rstrip("-") for tok in seq_raw.split(" ")] if seq_raw else []
        ranks = (ranks + [""] * len(SECTIONAL_POINTS))[:len(SECTIONAL_POINTS)]

        row = dict(zip(SECTIONAL_POINTS, ranks))
        times = [_clean(tds[i]) for i in range(3, 11)]
        row.update(dict(zip(SECTIONAL_TIME_LABELS, times)))
        row["경주기록"] = _clean(tds[11])
        result[post_no] = row
    return result


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"collected_dates": []}


def _save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="부산경남 전체 경주결과 수집")
    parser.add_argument("--meet", default="3")
    parser.add_argument("--months", type=int, default=None, help="오늘부터 N개월 전까지 백필")
    parser.add_argument("--incremental", action="store_true", help="상태 파일 기준 신규 날짜만 수집")
    parser.add_argument("--max-pages", type=int, default=60, help="날짜목록 페이지네이션 안전장치")
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    state = _load_state()
    collected = set(state["collected_dates"])

    cutoff = None
    if args.months:
        cutoff = date.today() - timedelta(days=30 * args.months)

    # 1) 날짜 목록 수집 (페이지네이션)
    all_dates: list[str] = []
    for page in range(1, args.max_pages + 1):
        dates = list_race_dates(args.meet, page)
        if not dates:
            break
        all_dates.extend(dates)
        oldest = min(dates)
        oldest_d = date(int(oldest[:4]), int(oldest[4:6]), int(oldest[6:8]))
        if args.incremental and oldest in collected:
            break
        if cutoff and oldest_d < cutoff:
            break
        time.sleep(args.delay)

    all_dates = sorted(set(all_dates))
    if cutoff:
        all_dates = [d for d in all_dates if date(int(d[:4]), int(d[4:6]), int(d[6:8])) >= cutoff]
    if args.incremental:
        all_dates = [d for d in all_dates if d not in collected]

    print(f"수집 대상 날짜 {len(all_dates)}개: {all_dates[:3]}...{all_dates[-3:] if len(all_dates) > 3 else ''}", flush=True)

    meta_path = OUT_DIR / f"race_meta_{args.meet}.csv"
    field_path = OUT_DIR / f"race_field_{args.meet}.csv"
    field_cols = ["경주일자", "경주번호"] + FIELD_COLUMNS

    def _append(path: Path, rows: list[dict], cols: list[str]):
        if not rows:
            return
        file_exists = path.exists()
        with path.open("a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            if not file_exists:
                writer.writeheader()
            writer.writerows(rows)

    total_meta, total_field = 0, 0
    for i, rc_date in enumerate(all_dates):
        race_nos = list_races_for_date(args.meet, rc_date)
        print(f"[{i+1}/{len(all_dates)}] {rc_date}: {len(race_nos)}개 경주", flush=True)
        time.sleep(args.delay)

        day_meta, day_field = [], []
        for rc_no in race_nos:
            try:
                meta, field = fetch_race_detail(args.meet, rc_date, rc_no)
            except requests.RequestException as e:
                print(f"  {rc_date}-{rc_no}R 실패: {e}", file=sys.stderr, flush=True)
                continue
            day_meta.append(meta)
            for row in field:
                row["경주일자"] = rc_date
                row["경주번호"] = rc_no
                day_field.append(row)
            time.sleep(args.delay)

        # 날짜 단위로 즉시 저장 + 상태 갱신 (중간에 끊겨도 처음부터 다시 안 해도 됨)
        _append(meta_path, day_meta, META_COLUMNS)
        _append(field_path, day_field, field_cols)
        total_meta += len(day_meta)
        total_field += len(day_field)
        collected.add(rc_date)
        state["collected_dates"] = sorted(collected)
        _save_state(state)

    print(f"\n경주 {total_meta}건, 출전기록 {total_field}건 수집 완료", flush=True)
    print(f"-> {meta_path}\n-> {field_path}", flush=True)


if __name__ == "__main__":
    main()
