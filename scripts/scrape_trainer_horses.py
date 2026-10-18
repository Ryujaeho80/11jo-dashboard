"""조교사(마방) 기준으로 소속마 전체 현황을 race.kra.co.kr에서 긁어온다.

공공데이터포털 API와 달리 이 경로는:
- 서비스키/할당량 제한이 없음 (공개 웹페이지)
- 마주명을 바로 포함하고 있어 "보유마 식별" 문제를 API 승인 없이 해결함
- 레이팅·등급·전적 요약까지 한 번에 제공

사용법:
    python scripts/scrape_trainer_horses.py --tr-no 070302 --meet 3

주의: 공개 웹페이지를 파싱하는 방식이라 KRA가 페이지 구조를 바꾸면 깨질 수 있음.
너무 자주 호출하지 말 것(하루 1~2회면 충분 — 소속마 현황이 분 단위로 바뀌지 않음).
"""
import argparse
import csv
import html as ihtml
import re
import sys
from pathlib import Path

import requests

BASE = "https://race.kra.co.kr/trainer"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

COLUMNS = [
    "순", "마번", "마명", "마주명", "조번", "등급", "레이팅",
    "산지", "성별", "연령", "데뷔일자", "전적", "비고",
]


def _clean(txt: str) -> str:
    txt = re.sub(r"<[^>]+>", "", txt)
    return ihtml.unescape(txt).strip()


def fetch_trainer_profile(tr_no: str, meet: str = "3") -> dict:
    """조교사 인적사항(생년월일, 소속조 등)을 가져온다."""
    resp = requests.post(
        f"{BASE}/profileTrainerPersonItem.do",
        data={"argOrderBy": "0", "trNo": tr_no, "meet": meet, "Act": "10", "Sub": "1"},
        headers=HEADERS,
        timeout=30,
    )
    resp.encoding = "euc-kr"
    text = resp.text
    name = re.search(r"<span>성명</span>([^<]+)", text)
    group = re.search(r"<span>소속조</span>([^<]+)", text)
    return {
        "tr_no": tr_no,
        "tr_name": name.group(1).strip() if name else None,
        "group": group.group(1).strip() if group else None,
    }


def fetch_trainer_horses(tr_no: str, meet: str = "3") -> list[dict]:
    """조교사의 위탁관리말(소속마) 전체 목록을 가져온다."""
    resp = requests.post(
        f"{BASE}/TrainerTrustManagehorse.do",
        data={"argOrderBy": "0", "trNo": tr_no, "meet": meet, "Act": "10", "Sub": "1"},
        headers=HEADERS,
        timeout=30,
    )
    resp.encoding = "euc-kr"
    content = resp.text

    tbodies = re.findall(r"<tbody>(.*?)</tbody>", content, re.S)
    if not tbodies:
        return []
    tbody = max(tbodies, key=len)  # 말 목록 테이블이 가장 큰 tbody

    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", tbody, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 11:
            continue
        horse_cell = tds[1]
        m = re.search(r"goPage5\('(\d+)'\)", horse_cell)
        hr_no = m.group(1) if m else ""
        hr_name = _clean(horse_cell)
        rest = [_clean(td) for td in tds[2:]]
        row = [_clean(tds[0]), hr_no, hr_name] + rest
        rows.append(dict(zip(COLUMNS, row)))
    return rows


def main():
    parser = argparse.ArgumentParser(description="조교사 소속마 현황 수집")
    parser.add_argument("--tr-no", required=True, help="조교사번호 (예: 070302)")
    parser.add_argument("--meet", default="3", help="1=서울 2=제주 3=영남(부산경남)")
    parser.add_argument(
        "--out", default=None, help="저장할 CSV 경로 (기본: data/processed/<조교사명>_소속마.csv)"
    )
    args = parser.parse_args()

    profile = fetch_trainer_profile(args.tr_no, args.meet)
    horses = fetch_trainer_horses(args.tr_no, args.meet)

    if not horses:
        print("소속마를 찾지 못했습니다. tr_no/meet 값을 확인하세요.", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.out) if args.out else Path(
        f"data/processed/{profile['tr_name']}_{profile['group']}_소속마.csv"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(horses)

    print(f"조교사: {profile['tr_name']} ({profile['group']}, 조교사번호 {profile['tr_no']})")
    print(f"소속마 {len(horses)}두 -> {out_path}")


if __name__ == "__main__":
    main()
