import time
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime

THEATER_CODE = "0013"
THEATER_KEYWORD = "용산아이파크몰"
THEATER_NAME = "CGV 용산아이파크몰"
MOVIE_NAME = "듄-파트 2 특별판"
PLAY_DATE = "20261202"

STATE_FILE = Path(__file__).with_name("open_alert_state.json")
BOOKING_URL = "https://cgv.co.kr/cnm/movieBook"


def normalize(text):
    return re.sub(r"[^가-힣a-zA-Z0-9]", "", str(text)).lower()


def fetch_timetable():
    npx = "npx.cmd" if sys.platform == "win32" else "npx"

    cmd = [
        npx, "--yes", "daiso", "get", "/api/cgv/timetable",
        "--keyword", THEATER_KEYWORD,
        "--theaterCode", THEATER_CODE,
        "--playDate", PLAY_DATE,
        "--json",
    ]

    for attempt in range(1, 4):
        print(f"CGV 시간표 조회 시도 {attempt}/3")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
            )

            raw = proc.stdout.strip()
            start = raw.find("{")
            end = raw.rfind("}")

            if start < 0 or end < 0:
                raise RuntimeError(
                    proc.stderr.strip() or "응답에서 JSON을 찾을 수 없습니다."
                )

            payload = json.loads(raw[start:end + 1])

            if not payload.get("success"):
                error = payload.get("error", {})
                raise RuntimeError(
                    error.get("message", "CGV 시간표 조회 실패")
                )

            return payload.get("data", {}).get("timetable") or []

        except Exception as error:
            print(f"조회 시도 {attempt} 실패: {error}")

            if attempt == 3:
                raise RuntimeError(
                    f"3회 재시도 후에도 조회 실패: {error}"
                )

            time.sleep(15)


def send_notification(rows):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        raise RuntimeError("NTFY_TOPIC secret이 설정되지 않았습니다.")

    times = sorted({
        str(row.get("startTime", "시간 미정"))
        for row in rows
    })

    message = (
        f"{MOVIE_NAME} 예매 오픈 감지!\n\n"
        f"극장: {THEATER_NAME}\n"
        f"날짜: 2026-12-02\n"
        f"상영 시간: {', '.join(times)}\n\n"
        f"예매 페이지: {BOOKING_URL}"
    )

    url = "https://ntfy.sh/" + urllib.parse.quote(topic)
    request = urllib.request.Request(
        url,
        data=message.encode("utf-8"),
        headers={
            "Title": "CGV Booking Open",
            "Priority": "high",
            "Tags": "movie_camera,ticket",
            "Content-Type": "text/plain; charset=utf-8",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()


def main():
    print(f"[{datetime.now()}] 상영 시간표 확인 시작")

    rows = fetch_timetable()
    target = normalize(MOVIE_NAME)

    matches = [
        row for row in rows
        if row.get("theaterCode") == THEATER_CODE
        and target in normalize(row.get("movieName", ""))
    ]

    print(f"검색된 상영 회차: {len(matches)}")

    state = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))

    if matches and not state.get("alerted"):
        send_notification(matches)
        state["alerted"] = True
        state["alerted_at"] = datetime.now().isoformat()
        print("예매 오픈 알림 전송 완료")

    elif matches:
        print("이미 알림을 보낸 상영작입니다.")

    else:
        print("아직 해당 영화의 상영 시간표가 없습니다.")

    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"조회 실패: {error}", file=sys.stderr)
        sys.exit(1)

