if __name__ == "__main__":
    today_dt = datetime.now()
    today_str = today_dt.strftime("%Y년 %m월 %d일")
    
    departures = fetch_flights(API_URL_DEPARTURE, "출발편", today_dt)
    arrivals = fetch_flights(API_URL_ARRIVAL, "도착편", today_dt)

    # HTML 텍스트 생성
    html = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>인천공항 비정상 운항 현황</title>
        <style>
            body {{ font-family: sans-serif; line-height: 1.6; padding: 20px; max-width: 800px; margin: auto; }}
            h2 {{ color: #333; border-bottom: 2px solid #ccc; padding-bottom: 5px; }}
            ul {{ list-style-type: none; padding: 0; }}
            li {{ padding: 8px; border-bottom: 1px solid #eee; }}
            .cancel {{ color: red; font-weight: bold; }}
            .delay {{ color: orange; font-weight: bold; }}
        </style>
    </head>
    <body>
        <h1>📅 인천국제공항 비정상 운항 보고서 ({today_str})</h1>
        
        <h2>🛫 출발편 (총 {len(departures)}건)</h2>
        <ul>
    """
    
    if not departures:
        html += "<li>결항 또는 헤비 딜레이된 출발편이 없습니다.</li>"
    else:
        for item in departures:
            html += f"<li>[{item['flight']}] [{item['airport']}] [{item['scheduled']}] -> <strong>{item['estimated']}</strong></li>"
            
    html += """
        </ul>
        <h2>🛬 도착편 (총 {len(arrivals)}건)</h2>
        <ul>
    """
    
    if not arrivals:
        html += "<li>결항 또는 헤비 딜레이된 도착편이 없습니다.</li>"
    else:
        for item in arrivals:
            html += f"<li>[{item['flight']}] [{item['airport']}] [{item['scheduled']}] -> <strong>{item['estimated']}</strong></li>"

    html += """
        </ul>
        <p style="color:gray; font-size:12px;">※ 이 데이터는 30분 주기로 자동 업데이트됩니다.</p>
    </body>
    </html>
    """

    # index.html 파일로 저장
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
