"""인천공항 여객편 운항현황 수집기 (안내데스크용)

GitHub Actions가 주기적으로 실행합니다.
1. 인천공항 공공 API에서 오늘 출발·도착편 전체를 받아옵니다.
2. 코드쉐어편을 실제 운항편(마스터) 하나로 묶습니다.
3. 직전 결과(배포된 data.json)와 비교해 상태·시간·게이트·카운터 변경 이력을 남깁니다.
4. site/ 폴더에 index.html + data.json 을 만들어 GitHub Pages로 배포합니다.

API 키는 저장소 Settings > Secrets 의 SERVICE_KEY 로만 넣고, 코드에 적지 마세요.
"""

import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone

import requests

KST = timezone(timedelta(hours=9))
SERVICE_KEY = os.environ.get("SERVICE_KEY", "").strip()
BASE = "apis.data.go.kr/B551177/StatusOfPassengerFlightsOdp"
ENDPOINTS = {"D": "getPassengerDeparturesOdp", "A": "getPassengerArrivalsOdp"}

# 이 값 이상 늦어지면 '비정상(지연)'으로 분류해 이력을 추적합니다. 화면에서는 기준을 따로 고를 수 있습니다.
DELAY_TRACK_MIN = 30
ABNORMAL_STATUS = ("결항", "회항", "지연", "취소", "CANCEL", "CNX", "DIVERT", "DELAY")
TERMINAL = {"P01": "T1", "P02": "T1 탑승동", "P03": "T2"}
TRACKED_FIELDS = {"status": "현황", "est": "변경시각", "gate": "게이트", "chkin": "체크인카운터"}

OUT_DIR = "site"
PREV_FILE = os.environ.get("PREV_DATA_FILE", "prev_data.json")  # 워크플로가 배포본에서 내려받아 둠
MOCK_DIR = os.environ.get("MOCK_DIR")  # 로컬 테스트용: D.json / A.json 을 API 응답 대신 사용


def g(row, *names):
    """필드명 대소문자 차이를 흡수해서 값을 꺼냅니다."""
    lower = {k.lower(): v for k, v in row.items()}
    for n in names:
        v = lower.get(n.lower())
        if v not in (None, "", "-", " "):
            return str(v).strip()
    return ""


def call_api(direction):
    """한 방향(출발/도착) 전체 목록을 받아옵니다. (items, error) 반환."""
    if MOCK_DIR:
        with open(os.path.join(MOCK_DIR, f"{direction}.json"), encoding="utf-8") as f:
            return extract_items(json.load(f))

    if not SERVICE_KEY:
        return [], "SERVICE_KEY 시크릿이 설정되지 않았습니다."

    params = {"serviceKey": SERVICE_KEY, "from_time": "0000", "to_time": "2400",
              "type": "json", "lang": "K"}
    last_err = ""
    for scheme in ("https", "http"):
        url = f"{scheme}://{BASE}/{ENDPOINTS[direction]}"
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            try:
                data = r.json()
            except ValueError:
                return [], f"API가 JSON이 아닌 응답을 보냄: {r.text[:200]}"
            items, err = extract_items(data)
            if err:
                return [], err
            total = int(data.get("response", {}).get("body", {}).get("totalCount") or 0)
            # 한 번에 다 안 오면 페이지를 넘겨 받습니다.
            page = 1
            while total and len(items) < total and page < 20:
                page += 1
                r = requests.get(url, params={**params, "numOfRows": 500, "pageNo": page}, timeout=30)
                more, err = extract_items(r.json())
                if err or not more:
                    break
                items += more
            return items, None
        except Exception as e:  # 네트워크 오류 → 다음 scheme 시도
            last_err = f"{type(e).__name__}: {e}"
    return [], f"API 호출 실패 ({last_err})"


def extract_items(data):
    resp = data.get("response", {})
    code = str(resp.get("header", {}).get("resultCode", "00"))
    if code not in ("00", "0"):
        return [], f"API 오류 {code}: {resp.get('header', {}).get('resultMsg', '')}"
    items = resp.get("body", {}).get("items") or []
    if isinstance(items, dict):
        items = items.get("item", items)
    if isinstance(items, dict):
        items = [items]
    return list(items), None


def to_minutes(value, today):
    """'HHMM' 또는 'YYYYMMDDHHMM' → 오늘 0시 기준 분. 실패 시 None."""
    v = "".join(ch for ch in (value or "") if ch.isdigit())
    try:
        if len(v) == 12:
            dt = datetime.strptime(v, "%Y%m%d%H%M").replace(tzinfo=KST)
            return int((dt - today).total_seconds() // 60)
        if len(v) == 4:
            return int(v[:2]) * 60 + int(v[2:])
    except ValueError:
        pass
    return None


def hhmm(minutes):
    if minutes is None:
        return ""
    return f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}"


def normalize(rows, direction, today):
    """API 행 → 화면용 항공편 목록 (코드쉐어 병합)."""
    groups = {}
    for row in rows:
        flight = g(row, "flightId")
        if not flight:
            continue
        master = g(row, "masterflightid") or flight
        sched_raw = g(row, "scheduleDateTime")
        key = f"{direction}|{master}|{sched_raw}"
        grp = groups.setdefault(key, {"master": master, "rows": []})
        grp["rows"].append((flight, row))

    flights = []
    for key, grp in groups.items():
        # 마스터 편명 행을 대표로, 나머지는 코드쉐어 편명으로
        rows_ = sorted(grp["rows"], key=lambda fr: fr[0] != grp["master"])
        flight, row = rows_[0]
        codeshares = sorted({f for f, _ in rows_[1:] if f != flight})

        sched = to_minutes(g(row, "scheduleDateTime"), today)
        est = to_minutes(g(row, "estimatedDateTime"), today)
        if sched is not None and est is not None and len(g(row, "estimatedDateTime")) == 4:
            # HHMM만 오는 경우 자정 넘김 보정
            if est - sched < -720:
                est += 1440
            elif est - sched > 720:
                est -= 1440
        status = g(row, "remark")
        cancelled = any(s in status.upper() for s in ("결항", "취소", "CANCEL", "CNX"))
        delay = None if (cancelled or sched is None or est is None) else est - sched

        stops = [g(row, n) for n in ("firstopovername", "secstopovername", "thistopovername")]
        f = {
            "id": key,
            "dir": direction,
            "flight": flight,
            "codeshares": codeshares,
            "airline": g(row, "airline"),
            "airport": g(row, "airport"),
            "airportCode": g(row, "airportCode", "cityCode"),
            "via": [s for s in stops if s],
            "terminal": TERMINAL.get(g(row, "terminalId", "terminalid"), g(row, "terminalId", "terminalid")),
            "schedMin": sched,
            "sched": hhmm(sched),
            "estMin": None if cancelled else est,
            "est": "" if cancelled else hhmm(est),
            "estDay": 0 if (cancelled or est is None) else est // 1440,
            "delay": delay,
            "status": status,
            "gate": g(row, "gatenumber"),
            "chkin": g(row, "chkinrange", "chkinRange", "checkinrange"),
            "carousel": g(row, "carousel"),
            "exit": g(row, "exitnumber"),
            "intl": g(row, "typeOfFlight") != "D",
        }
        up = status.upper()
        f["abnormal"] = (cancelled or any(s in up for s in ABNORMAL_STATUS)
                         or (delay is not None and delay >= DELAY_TRACK_MIN))
        flights.append(f)
    return flights


def merge_history(current, prev_flights, now_hhmm):
    """직전 결과와 비교해 변경 이력/최초 감지 시각을 이어 붙입니다."""
    prev = {f["id"]: f for f in prev_flights}
    out = []
    for f in current:
        p = prev.pop(f["id"], None)
        f["changes"] = list(p.get("changes", [])) if p else []
        f["firstSeen"] = p.get("firstSeen") if p else None
        if p:
            for field, label in TRACKED_FIELDS.items():
                before, after = p.get(field, ""), f.get(field, "")
                if before != after and (before or after):
                    f["changes"].append({"t": now_hhmm, "k": label, "from": before, "to": after})
        if f["abnormal"] and not f["firstSeen"]:
            f["firstSeen"] = now_hhmm
        f["changes"] = f["changes"][-15:]
        out.append(f)
    # 이번 응답에서 빠졌지만 오늘 비정상이었던 편은 남겨 둡니다 (자정 전까지 누적).
    for p in prev.values():
        if p.get("abnormal") or p.get("firstSeen"):
            p["gone"] = True
            out.append(p)
    return out


def load_prev(date_key):
    try:
        with open(PREV_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("date") == date_key:
            return data
    except Exception:
        pass
    return None


def main():
    now = datetime.now(KST)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    date_key = now.strftime("%Y%m%d")
    now_hhmm = now.strftime("%H:%M")
    prev = load_prev(date_key)

    errors, flights = [], []
    for d in ("D", "A"):
        rows, err = call_api(d)
        prev_dir = [f for f in (prev or {}).get("flights", []) if f["dir"] == d]
        if err:
            errors.append(f"{'출발' if d == 'D' else '도착'}: {err}")
            flights += prev_dir  # 실패 시 직전 데이터 유지 (화면에 오류 표시)
            continue
        flights += merge_history(normalize(rows, d, today), prev_dir, now_hhmm)

    flights.sort(key=lambda f: (f["schedMin"] if f["schedMin"] is not None else 9999, f["flight"]))
    out = {
        "date": date_key,
        "updatedAt": now.isoformat(timespec="seconds"),
        "lastSuccessAt": now.isoformat(timespec="seconds") if not errors
                         else (prev or {}).get("lastSuccessAt"),
        "errors": errors,
        "flights": flights,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "data.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    shutil.copy("index.html", os.path.join(OUT_DIR, "index.html"))

    ab = sum(1 for f in flights if f["abnormal"])
    print(f"{now_hhmm} 수집 완료: 전체 {len(flights)}편, 비정상 {ab}편, 오류 {errors or '없음'}")
    # 두 방향 모두 실패하고 이전 데이터도 없으면 실패로 표시 (Actions에서 알림 받기)
    if len(errors) == 2 and not prev:
        sys.exit(1)


if __name__ == "__main__":
    main()
