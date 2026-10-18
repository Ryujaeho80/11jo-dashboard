"""매일 자동 실행용 통합 업데이트 스크립트.

순서: 소속마 목록 갱신 -> 말별 경주이력 갱신(28두) -> 경주결과 증분수집(신규 경주일만)
     -> 분석 재계산(최종점수, 상대마 비교). 실패해도 다음 단계는 가능한 만큼 계속 진행하고
     마지막에 전체 성공/실패 요약을 로그 파일에 남긴다.

사용법 (수동 실행도 가능):
    python scripts/daily_update.py

Windows 작업 스케줄러 등록 예시:
    schtasks /create /tn "경주마_데이터_일일수집" /tr "python C:\\...\\scripts\\daily_update.py" /sc daily /st 06:00
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LOG_PATH = Path("data/processed/daily_update_log.txt")
TRAINER_NO = "070302"  # 손병철
MEET = "3"


def run_step(name: str, cmd: list[str]) -> bool:
    print(f"\n{'='*50}\n[{name}] 시작\n{'='*50}", flush=True)
    result = subprocess.run([sys.executable, *cmd], capture_output=True, text=True)
    ok = result.returncode == 0
    status = "성공" if ok else "실패"
    print(f"[{name}] {status} (exit={result.returncode})", flush=True)
    if result.stdout:
        print(result.stdout[-1500:], flush=True)
    if not ok and result.stderr:
        print(result.stderr[-1500:], file=sys.stderr, flush=True)
    return ok


def main():
    started = datetime.now()
    results = {}

    results["소속마 목록"] = run_step(
        "1/4 소속마 목록 갱신",
        ["scripts/scrape_trainer_horses.py", "--tr-no", TRAINER_NO, "--meet", MEET],
    )
    results["말별 경주이력"] = run_step(
        "2/4 말별 경주이력 갱신",
        ["scripts/scrape_horse_history.py",
         "--horses-csv", "data/processed/손병철_11조_소속마.csv", "--meet", MEET, "--delay", "0.5"],
    )
    results["경주결과 증분수집"] = run_step(
        "3/4 부산경남 경주결과 증분수집",
        ["scripts/scrape_race_results.py", "--incremental", "--delay", "0.4"],
    )
    results["최종점수 재계산"] = run_step(
        "4/4 최종 출마등록 점수 재계산", ["scripts/final_entry_score.py"],
    )
    results["상대마 비교 재계산"] = run_step(
        "4/5 상대마 비교표 재계산", ["scripts/rival_comparison.py"],
    )
    results["거리별 분해 재계산"] = run_step(
        "5/7 거리별 성적 분해 재계산", ["scripts/distance_breakdown.py"],
    )
    results["말별 인사이트 재계산"] = run_step(
        "6/7 최적거리·양면형·주의사항 재계산", ["scripts/horse_insights.py"],
    )
    results["대시보드 재생성"] = run_step(
        "7/7 대시보드 HTML 재생성", ["scripts/generate_dashboard.py"],
    )

    finished = datetime.now()
    summary_lines = [
        f"\n[{finished:%Y-%m-%d %H:%M:%S}] 일일 업데이트 완료 (소요 {(finished-started).seconds}초)",
    ]
    for name, ok in results.items():
        summary_lines.append(f"  - {name}: {'OK' if ok else 'FAIL'}")
    summary = "\n".join(summary_lines)
    print(summary, flush=True)

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(summary + "\n")

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
