import os, json, pytz
import google.generativeai as genai
from polygon import RESTClient
from datetime import datetime

# --- 配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
POLY_KEY = os.environ.get("POLYGON_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
HIVE_FILE = "hive.json"

client = RESTClient(api_key=POLY_KEY)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel(AI_MODEL_NAME)

def is_market_open():
    tz_ny = pytz.timezone('US/Eastern')
    tz_hk = pytz.timezone('Asia/Hong_Kong')
    now_ny = datetime.now(tz_ny)
    now_hk = datetime.now(tz_hk)
    # 美股或港股周一至周五 09:30 - 16:00
    us_open = now_ny.weekday() < 5 and (9 <= now_ny.hour < 16)
    hk_open = now_hk.weekday() < 5 and (9 <= now_hk.hour < 16)
    return us_open or hk_open

def load_hive():
    if os.path.exists(HIVE_FILE):
        try:
            with open(HIVE_FILE, "r", encoding='utf-8') as f: return json.load(f)
        except: pass
    return {"drones": []}

def save_hive(data):
    with open(HIVE_FILE, "w", encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def patrol():
    hive = load_hive()
    if not is_market_open():
        print("☕ 非交易时段，工蜂休息。")
        return

    for drone in hive.get("drones", []):
        try:
            print(f"工蜂 {drone['name']} 正在巡检...")
            market_data = {}
            for ticker in drone["portfolio"]:
                try:
                    snap = client.get_snapshot_ticker("stocks", ticker)
                    market_data[ticker] = {
                        "price": getattr(snap.last_trade, 'p', 0),
                        "change_p": getattr(snap.todays_change_percent, 'p', 0)
                    }
                except: continue
            
            if not market_data: continue

            prompt = f"你是工蜂 {drone['name']}。逻辑：{drone['logic']}。当前数据：{market_data}。请简短分析并给建议。"
            response = model.generate_content(prompt)
            
            new_log = {
                "time": datetime.now().strftime("%H:%M"),
                "data": market_data,
                "advice": response.text[:200]
            }
            drone.setdefault("logs", []).append(new_log)
            drone["logs"] = drone["logs"][-10:] # 只留最近10条
        except Exception as e:
            print(f"错误: {e}")
    
    save_hive(hive)

if __name__ == "__main__":
    patrol()