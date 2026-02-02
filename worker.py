import os, json
import google.generativeai as genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

# --- 配置 ---
client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel("gemini-3-flash-preview")

def fetch_market_data(d):
    obs = {}
    for t in d["portfolio"]:
        try:
            if d['focus'] == 'stock':
                s = client_poly.get_snapshot_ticker("stocks", t)
                obs[t] = {"price": s.last_trade.p, "change": s.todays_change_percent}
            else:
                o = client_poly.list_snapshot_options_chain(t, limit=2)
                obs[t] = [{"strike": x.details.strike_price, "price": x.last_trade.p} for x in o]
        except: obs[t] = "N/A"
    return obs

def patrol_and_evolve():
    drones = supabase.table("drones").select("*").execute().data
    for d in drones:
        try:
            print(f"--- {d['name']} ({d['type']}) 执行中 ---")
            m_data = fetch_market_data(d)
            
            # 决策并提取经验
            prompt = f"""你是兵蜂 {d['name']}。性格：{d['persona']}。历史教训：{d.get('memory')}
            现金：{d['balance']} | 持仓：{d['positions']} | 行情：{m_data}
            返回JSON：{{"action":"BUY/SELL/HOLD","symbol":"...","qty":0,"price":0,"reason":"...","learning":"本次学习心得"}}"""
            
            res = model.generate_content(prompt).text.strip()
            cmd = json.loads(res.replace("```json", "").replace("```", ""))
            
            update = {}
            if cmd['action'] == 'BUY' and d['balance'] >= (cmd['qty'] * cmd['price']):
                update['balance'] = d['balance'] - (cmd['qty'] * cmd['price'])
                new_pos = d.get('positions', {}).copy()
                new_pos[cmd['symbol']] = new_pos.get(cmd['symbol'], 0) + cmd['qty']
                update['positions'] = new_pos
            
            # 记录学习与峰值
            update['memory'] = f"最近总结：{cmd['learning']}"
            current_bal = update.get('balance', d['balance'])
            update['peak_balance'] = max(d.get('peak_balance', 0), current_bal)
            
            # 日志记录
            new_log = {"t": datetime.now().strftime("%H:%M"), "m": cmd['reason']}
            update['logs'] = (d.get("logs", []) + [new_log])[-10:]
            
            supabase.table("drones").update(update).eq("id", d["id"]).execute()
            print(f"✅ {d['name']} 状态已更新")

        except Exception as e: print(f"❌ {d['name']} 报错: {e}")

if __name__ == "__main__":
    patrol_and_evolve()