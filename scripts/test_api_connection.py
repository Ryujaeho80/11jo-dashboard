"""4개 KRA 공공데이터 API에 실제로 1회씩 호출해 응답 구조를 검증한다.
.env의 KRA_SERVICE_KEY를 사용하며, 키 값 자체는 출력하지 않는다.
"""
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

SERVICE_KEY = os.environ["KRA_SERVICE_KEY"]
MEET = os.environ.get("KRA_MEET_CODE", "3")

ENDPOINTS = {
    "경주마_성적정보": {
        "url": "https://apis.data.go.kr/B551015/API15_2/raceHorseResult_2",
        "params": {"pageNo": 1, "numOfRows": 3, "meet": MEET, "_type": "json"},
    },
    "경주마_레이팅정보": {
        "url": "https://apis.data.go.kr/B551015/API77/raceHorseRating",
        "params": {"pageNo": 1, "numOfRows": 3, "_type": "json"},
    },
    "조교사_상세정보": {
        "url": "https://apis.data.go.kr/B551015/API19_1/trainerInfo_1",
        "params": {"pageNo": 1, "numOfRows": 3, "meet": MEET, "_type": "json"},
    },
    "경주마_상세정보": {
        "url": "https://apis.data.go.kr/B551015/API8_2/raceHorseInfo_2",
        "params": {"pageNo": 1, "numOfRows": 3, "meet": MEET, "_type": "json"},
    },
}

for name, spec in ENDPOINTS.items():
    print(f"\n{'='*60}\n{name}\n{'='*60}")
    params = dict(spec["params"])
    params["serviceKey"] = SERVICE_KEY
    try:
        resp = requests.get(spec["url"], params=params, timeout=10)
        print(f"status={resp.status_code}")
        text = resp.text
        try:
            data = resp.json()
            print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
        except ValueError:
            print(text[:1500])
    except requests.RequestException as e:
        print(f"요청 실패: {e}")
