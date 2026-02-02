import os
import json
import google.generativeai as genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime

# --- 配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel(AI_MODEL_NAME)

def fetch_data(d):
    results = {}
    for ticker in d["portfolio"]:
        try:
            if d['focus'] == 'stock':
                snap = client_poly.get_snapshot_ticker("stocks", ticker)
                results[ticker] = {"price": snap.last_trade.p, "change": snap.todays_change_percent}
            else:
                opts = client_poly.list_snapshot_options_chain(ticker, limit=3)
                results[ticker] = [{"strike": o.details.strike_price, "price": o.last_trade.p, "type": o.details.contract_type} for o in opts]
        except: results[ticker] = "Data Unavailable"
    return results

def patrol():
    drones = supabase.table("drones").select("*").execute().data
    for d in drones:
        try:
            print(f"--- {d['name']} ({d['type']}) 执行中 ---")
            market_data = fetch_data(d)
            
            if d['type'] == 'soldier':
                prompt = f"交易员兵蜂 {d['name']}。性格：{d['persona']}。资金：{d['balance']}。持仓：{d['positions']}。行情：{market_data}。输出纯JSON：{{'action': 'BUY/SELL/HOLD', 'symbol': '代码', 'qty': 数量, 'price': 价格, 'reason': '理由'}}"
            else:
                prompt = f"工蜂 {d['name']}。逻辑：{d['logic']}。数据：{market_data}。请简短分析建议。"

            res = model.generate_content(prompt).text.strip()
            clean_res = res.replace("```json", "").replace("```", "").strip()

            update_payload = {}
            log_info = ""

            if d['type'] == 'soldier':
                decision = json.loads(clean_res)
                log_info = f"{decision['action']} {decision['qty']} {decision['symbol']}: {decision['reason']}"
                
                # 模拟简单账本更新
                if decision['action'] == 'BUY':
                    cost = decision['qty'] * decision['price']
                    if d['balance'] >= cost:
                        update_payload['balance'] = d['balance'] - cost
                        new_pos = d['positions'].copy()
                        new_pos[decision['symbol']] = new_pos.get(decision['symbol'], 0) + decision['qty']
                        update_payload['positions'] = new_pos
                elif decision['action'] == 'SELL':
                    # 此处可添加卖出逻辑...
                    pass
            else:
                log_info = clean_res[:150]

            # 统一更新数据库
            new_log = {"time": datetime.now().strftime("%H:%M"), "info": log_info}
            update_payload['logs'] = (d.get("logs", []) + [new_log])[-10:]
            supabase.table("drones").update(update_payload).eq("id", d["id"]).execute()
            
        except Exception as e:
            print(f"单位 {d['name']} 异常: {e}")

if __name__ == "__main__":
    patrol()