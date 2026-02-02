import os, pytz
import google.generativeai as genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime

# --- 配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
POLY_KEY = os.environ.get("POLYGON_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
SB_URL = os.environ.get("SUPABASE_URL")
SB_KEY = os.environ.get("SUPABASE_KEY")

# 初始化所有客户端
supabase = create_client(SB_URL, SB_KEY)
client_poly = RESTClient(api_key=POLY_KEY)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel(AI_MODEL_NAME)

def patrol():
    # 1. 从 Supabase 读取所有活跃工蜂
    response = supabase.table("drones").select("*").execute()
    drones = response.data

    for d in drones:
        try:
            print(f"工蜂 {d['name']} 出发巡检...")
            market_data = {}
            for ticker in d["portfolio"]:
                snap = client_poly.get_snapshot_ticker("stocks", ticker)
                market_data[ticker] = {
                    "price": getattr(snap.last_trade, 'p', 0),
                    "change_p": getattr(snap.todays_change_percent, 'p', 0)
                }
            
            # 2. 调用 Gemini 3 Flash Preview 分析
            prompt = f"你是工蜂 {d['name']}。逻辑：{d['logic']}。数据：{market_data}。请简短分析。"
            res = model.generate_content(prompt)
            
            # 3. 准备新日志
            new_log = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "data": market_data,
                "advice": res.text[:200]
            }
            
            # 保持日志长度 (保留最近 10 条)
            current_logs = d.get("logs", [])
            current_logs.append(new_log)
            updated_logs = current_logs[-10:]

            # 4. 直接写回 Supabase
            supabase.table("drones").update({
                "logs": updated_logs,
                "status": "ACTIVE"
            }).eq("id", d["id"]).execute()
            
        except Exception as e:
            print(f"工蜂 {d['name']} 迷航: {e}")

if __name__ == "__main__":
    patrol()