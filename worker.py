import os
import google.generativeai as genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime
import json

# --- 配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel(AI_MODEL_NAME)

def get_market_data(d):
    data = {}
    for ticker in d["portfolio"]:
        if d['focus'] == 'stock':
            snap = client_poly.get_snapshot_ticker("stocks", ticker)
            data[ticker] = {"price": snap.last_trade.p, "change": snap.todays_change_percent}
        else:
            # 获取期权快照 (简化逻辑：获取该正股下最近的一个看涨看跌价格)
            opt = client_poly.list_snapshot_options_chain(ticker, limit=2)
            data[ticker] = [{"strike": o.details.strike_price, "price": o.last_trade.p} for o in opt]
    return data

def patrol_and_trade():
    drones = supabase.table("drones").select("*").execute().data
    for d in drones:
        try:
            print(f"[{d['type'].upper()}] {d['name']} 正在扫描...")
            market_data = get_market_data(d)
            
            # 决策 Prompt
            prompt = f"""
            你是{d['name']}，一名{d['persona']}。
            当前余额: ${d.get('balance', 0)}
            持仓: {d.get('positions', {})}
            行情: {market_data}
            
            任务：决定操作。
            输出纯JSON格式：{{"action": "BUY/SELL/HOLD", "symbol": "代码", "qty": 数量, "reason": "理由"}}
            """
            res = model.generate_content(prompt)
            decision = json.loads(res.text.strip().replace("```json", "").replace("```", ""))

            # 模拟执行与账本更新 (仅兵蜂)
            if d['type'] == 'soldier' and decision['action'] != 'HOLD':
                # 这里可以添加简单的买入卖出逻辑更新 balance 和 positions
                print(f"执行决策: {decision['reason']}")

            # 更新日志
            new_log = {"time": datetime.now().strftime("%H:%M"), "action": decision['action'], "reason": decision['reason']}
            logs = (d.get("logs", []) + [new_log])[-10:]
            supabase.table("drones").update({"logs": logs}).eq("id", d["id"]).execute()
            
        except Exception as e:
            print(f"执行失败: {e}")

if __name__ == "__main__":
    patrol_and_trade()