import requests
import json
import os
from datetime import datetime, timedelta

# GitHub Secrets에서 인증키를 불러옵니다
SERVICE_KEY = os.environ.get("SERVICE_KEY")

# 여객기 운항 현황 정보 조회 오퍼레이션 API 엔드포인트
API_URL_DEPARTURE = "http://apis.data.go.kr/B551177/StatusOfPassengerFlightsOdp/getPassengerDeparturesOdp"
API_URL_ARRIVAL = "http://apis.data.go.kr/B551177/StatusOfPassengerFlightsOdp/getPassengerArrivalsOdp"

def format_time(t_str):
    if t_str and len(t_str) == 4:
        return f"{t_str[:2]}:{t_str[2:]}"
    return t_str

def calculate_delay_and_date(sch_time_str, est_time_str):
    try:
        sch_h, sch_m = int(sch_time_str[:2]), int(sch_time_str[2:])
        est_h, est_m = int(est_time_str[:2]), int(est_time_str[2:])
        
        sch_total_mins = (sch_h * 60) + sch_m
        est_total_mins = (est_h * 60) + est_m
        
        diff = est_total_mins - sch_total_mins
        is_next_day = False
        
        if diff < -720:  
            diff += 24 * 60
            is_next_day = True
        elif diff > 720:
            diff -= 24 * 60
            
        return diff, is_next_day
    except ValueError:
        return 0, False

def fetch_flights(api_url, direction, today_dt):
    if not SERVICE_KEY:
        print("API 키가 없습니다. GitHub Secrets 설정을 확인하세요.")
        return []
        
    params = {
        "serviceKey": SERVICE_KEY,
        "from_time": "0000",
        "to_time": "2400",
        "type": "json",
        "lang": "K"
    }

    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        
        data = response.json()
        flights = data.get('response', {}).get('body', {}).get('items', [])
        
        if isinstance(flights, dict) and 'item' in flights:
            flights = flights['item']
        if isinstance(flights, dict): 
            flights = [flights]
            
        abnormal_flights = []
        processed_masters = set()

        for flight in flights:
            flight_id = flight.get('flightId', '')
            master_id = flight.get('masterflightid', '')
            status = flight.get('remark', '')
            sch_time = flight.get('scheduleDateTime', '')
            est_time = flight.get('estimatedDateTime', '')
            airport = flight.get('airport', '미상') 

            check_id = master_id if master_id else flight_id
            if check_id in processed_masters:
                continue
            
            if status in ['결항', 'Cancel', 'CNX']:
                abnormal_flights.append({
                    "flight": flight_id,
                    "airport": airport,
                    "scheduled": format_time(sch_time),
                    "estimated": "[결항]"
                })
                processed_masters.add(check_id)
                continue

            if sch_time and est_time and sch_time != est_time:
                delay_mins, is_next_day = calculate_delay_and_date(sch_time, est_time)
                
                if delay_mins >= 180:
                    est_str = format_time(est_time)
                    if is_next_day:
                        tomorrow_dt = today_dt + timedelta(days=1)
                        tomorrow_str = tomorrow_dt.strftime("%m월 %d일")
                        est_str = f"[{tomorrow_str}] [{est_str}]"
                    else:
                        est_str = f"[{est_str}]"
                        
                    abnormal_flights.append({
                        "flight": flight_id,
                        "airport": airport,
                        "scheduled": format_time(sch_time),
                        "estimated": est_str
                    })
                    processed_masters.add(check_id)

        return abnormal_flights

    except Exception as e:
        print(f"[{direction}] 에러: {e}")
        return []


if __name__ == "__main__":
    # 한국 시간(KST) 세팅
    kst_now = datetime.utcnow() + timedelta(hours=9)
    today_str = kst_now.strftime("%Y년 %m월 %d일 %H:%M 기준")
    
    # 비고란 리셋을 위해 사용할 "오늘 날짜" 고유 키 (예: 20261011)
    date_key = kst_now.strftime("%Y%m%d")
    
    departures = fetch_flights(API_URL_DEPARTURE, "출발편", kst_now)
    arrivals = fetch_flights(API_URL_ARRIVAL, "도착편", kst_now)

    html = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>인천공항 비정상 운항 현황</title>
        <style>
            body {{ font-family: sans-serif; line-height: 1.6; padding: 20px; max-width: 800px; margin: auto; }}
            h2 {{ color: #333; border-bottom: 2px solid #ccc; padding-bottom: 5px; margin-top: 30px; }}
            ul {{ list-style-type: none; padding: 0; }}
            li {{ padding: 12px 8px; border-bottom: 1px solid #eee; display: flex; flex-direction: column; gap: 8px; }}
            .flight-info {{ font-size: 16px; word-break: keep-all; }}
            .remark-input {{ width: 100%; max-width: 500px; padding: 8px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; background-color: #f9f9f9; }}
            .remark-input:focus {{ outline: none; border-color: #0066cc; background-color: #fff; }}
        </style>
    </head>
    <body>
        <h1>📅 인천국제공항 비정상 운항 보고서</h1>
        <p style="color:gray;">업데이트 시간: {today_str}</p>
        
        <h2>🛫 출발편 (총 {len(departures)}건)</h2>
        <ul>
    """
    
    if not departures:
        html += "<li><div class='flight-info'>결항 또는 헤비 딜레이된 출발편이 없습니다.</div></li>"
    else:
        for item in departures:
            html += f"""
            <li>
                <div class="flight-info">[{item['flight']}] [{item['airport']}] [{item['scheduled']}] -> <strong>{item['estimated']}</strong></div>
                <input type="text" class="remark-input" data-flight="{item['flight']}" placeholder="여기에 비고를 입력하세요 (자동 임시저장)">
            </li>"""
            
    html += f"""
        </ul>
        <h2>🛬 도착편 (총 {len(arrivals)}건)</h2>
        <ul>
    """
    
    if not arrivals:
        html += "<li><div class='flight-info'>결항 또는 헤비 딜레이된 도착편이 없습니다.</div></li>"
    else:
        for item in arrivals:
            html += f"""
            <li>
                <div class="flight-info">[{item['flight']}] [{item['airport']}] [{item['scheduled']}] -> <strong>{item['estimated']}</strong></div>
                <input type="text" class="remark-input" data-flight="{item['flight']}" placeholder="여기에 비고를 입력하세요 (자동 임시저장)">
            </li>"""

    html += f"""
        </ul>
        <p style="color:gray; font-size:12px; margin-top:30px;">※ 이 데이터는 30분 주기로 자동 업데이트됩니다.</p>
        
        <script>
            document.addEventListener("DOMContentLoaded", function() {{
                const todayKey = "{date_key}"; // 파이썬에서 주입된 오늘 날짜 (예: 20261011)
                const inputs = document.querySelectorAll('.remark-input');

                // 1. 과거 날짜의 비고란 데이터 자동 삭제 (찌꺼기 데이터 청소)
                for (let i = 0; i < localStorage.length; i++) {{
                    let key = localStorage.key(i);
                    if (key && key.startsWith('remark_') && !key.includes(todayKey)) {{
                        localStorage.removeItem(key);
                    }}
                }}

                // 2. 현재 화면의 입력칸에 저장된 데이터 불러오기 및 입력 시 자동 저장
                inputs.forEach(input => {{
                    const flightId = input.getAttribute('data-flight');
                    const storageKey = `remark_${{todayKey}}_${{flightId}}`;

                    // 저장된 내용이 있으면 불러오기
                    if (localStorage.getItem(storageKey)) {{
                        input.value = localStorage.getItem(storageKey);
                    }}

                    // 글씨를 칠 때마다 즉시 로컬 스토리지에 저장
                    input.addEventListener('input', function() {{
                        localStorage.setItem(storageKey, this.value);
                    }});
                }});
            }});
        </script>
    </body>
    </html>
    """

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
