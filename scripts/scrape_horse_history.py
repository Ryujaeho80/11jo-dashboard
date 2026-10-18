"""말 1두 기준 마적사항(프로필) + 경주성적(경주별 시계열)을 race.kra.co.kr에서 긁어온다.

출주 전략(레이팅 추세, 등급 변동, 출주 간격, 거리 적합도)을 보려면 말이 뛴 경주 하나하나의
기록이 필요한데, 공공데이터 API는 "최근 1경주 스냅샷"만 주고 전체 이력 API는 하루 5회
할당량이라 사실상 못 쓴다. race.kra.co.kr의 "경주마정보 > 경주성적" 탭은 공개 웹페이지로
할당량 없이 말 1두당 경주 이력 전체(순위, 레이팅, 등급, 거리, 기수, 마체중, 주로상태 등)를
제공한다.

사용법 (조교사 소속마 CSV를 입력으로 전체 수집):
    python scripts/scrape_horse_history.py --horses-csv "data/processed/손병철_11조_소속마.csv"

단일 말만 테스트:
    python scripts/scrape_horse_history.py --hr-no 0057801 --meet 3
"""
import argparse
import csv
import html as ihtml
import re
import sys
import time
from pathlib import Path

import requests

BASE = "https://race.kra.co.kr/racehorse"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

RACE_COLUMNS = [
    "순", "경주일자", "개최지", "교류경주", "경주번호", "출주번호", "경주종류", "거리", "등급",
    "순위", "출주두수", "기수", "중량", "레이팅", "경주기록", "마체중", "마체중증감",
    "주로", "주로빠르기",
]

MEET_NAMES = {"1": "서울", "2": "제주", "3": "부산경남", "4": "영천"}


def _clean(txt: str) -> str:
    txt = re.sub(r"<[^>]+>", "", txt)
    return ihtml.unescape(txt).strip()


def _post(path: str, hr_no: str, meet: str) -> str:
    resp = requests.post(
        f"{BASE}/{path}",
        data={"hrNo": hr_no, "meet": meet, "Act": "08", "Sub": "1"},
        headers=HEADERS,
        timeout=30,
    )
    resp.encoding = "euc-kr"
    return resp.text


def fetch_horse_profile(hr_no: str, meet: str = "3") -> dict:
    """마적사항 탭: 레이팅, 등급, 마주, 조교사, 통산전적, 최근거래가 등 현재 스냅샷."""
    content = _post("profileHorseItem.do", hr_no, meet)
    rows = re.findall(r"<th scope=\"row\">\s*([^<]+?)\s*</th>\s*<td[^>]*>(.*?)</td>", content, re.S)
    profile = {"hr_no": hr_no, "meet": meet}
    for label, value in rows:
        profile[_clean(label)] = _clean(value)
    return profile


def fetch_horse_race_history(hr_no: str, meet: str = "3") -> list[dict]:
    """경주성적 탭: 경주별 순위/레이팅/등급/거리/기수/마체중/주로상태 시계열."""
    content = _post("profileRaceScore.do", hr_no, meet)
    tbodies = re.findall(r"<tbody>(.*?)</tbody>", content, re.S)
    if not tbodies:
        return []
    tbody = max(tbodies, key=len)

    records = []
    for tr in re.findall(r"<tr>(.*?)</tr>", tbody, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 14:
            continue
        seq = _clean(tds[0])
        date_cell = tds[1]
        m = re.search(r"goScore\(\"(\d+)\",\"(\d+)\",\"(\d+)\"\)", date_cell)
        rc_meet, rc_date, rc_no = m.groups() if m else ("", "", "")
        date_text = _clean(date_cell)  # 예: "2026/10/16-6R"

        post_no = _clean(tds[2])
        race_type = _clean(tds[3])
        distance = _clean(tds[4])
        grade = _clean(tds[5])
        rank_raw = _clean(tds[6])  # "9/14"
        rank, field_size = (rank_raw.split("/") + [""])[:2] if "/" in rank_raw else (rank_raw, "")
        jockey = _clean(tds[7])
        weight = _clean(tds[8])
        rating = _clean(tds[9])
        rc_time = _clean(tds[10])
        body_weight_raw = _clean(tds[11])  # "472(-2)"
        bw_m = re.match(r"(\d+)\(([+-]?\d+)\)", body_weight_raw)
        body_weight, body_weight_delta = bw_m.groups() if bw_m else (body_weight_raw, "")
        track = _clean(tds[12])
        track_speed = _clean(tds[13])

        venue = MEET_NAMES.get(rc_meet, rc_meet)
        is_interchange = bool(rc_meet) and rc_meet != meet  # 홈 경마장(meet)과 다르면 교류경주

        records.append({
            "순": seq,
            "경주일자": rc_date or date_text,
            "개최지": venue,
            "교류경주": "Y" if is_interchange else "",
            "경주번호": rc_no,
            "출주번호": post_no,
            "경주종류": race_type,
            "거리": distance,
            "등급": grade,
            "순위": rank,
            "출주두수": field_size,
            "기수": jockey,
            "중량": weight,
            "레이팅": rating,
            "경주기록": rc_time,
            "마체중": body_weight,
            "마체중증감": body_weight_delta,
            "주로": track,
            "주로빠르기": track_speed,
        })
    return records


def _read_horse_list(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser(description="말 경주이력(시계열) 수집")
    parser.add_argument("--hr-no", help="단일 마번 테스트용")
    parser.add_argument("--horses-csv", help="scrape_trainer_horses.py가 만든 소속마 CSV")
    parser.add_argument("--meet", default="3")
    parser.add_argument("--delay", type=float, default=1.0, help="요청 사이 대기(초) — 서버 배려")
    parser.add_argument("--out-dir", default="data/raw/race_history")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.hr_no:
        targets = [{"마번": args.hr_no, "마명": args.hr_no}]
    elif args.horses_csv:
        targets = _read_horse_list(Path(args.horses_csv))
    else:
        print("--hr-no 또는 --horses-csv 중 하나는 필요합니다.", file=sys.stderr)
        sys.exit(1)

    all_records = []
    for i, h in enumerate(targets):
        hr_no, hr_name = h["마번"], h.get("마명", h["마번"])
        print(f"[{i+1}/{len(targets)}] {hr_name} ({hr_no}) 수집 중...")
        try:
            history = fetch_horse_race_history(hr_no, args.meet)
        except requests.RequestException as e:
            print(f"  실패: {e}", file=sys.stderr)
            continue
        for rec in history:
            rec["마번"] = hr_no
            rec["마명"] = hr_name
        all_records.extend(history)
        print(f"  경주 {len(history)}건")
        if i < len(targets) - 1:
            time.sleep(args.delay)

    out_path = out_dir / "race_history_combined.csv"
    cols = ["마번", "마명"] + RACE_COLUMNS
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(all_records)

    print(f"\n총 {len(all_records)}개 경주 기록 -> {out_path}")


if __name__ == "__main__":
    main()
