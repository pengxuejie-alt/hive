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

def get_data(d):
    obs = {}
    for t in d["portfolio"]:
        try:
            if d['focus'] == 'stock':
                s = client_poly.get_snapshot_ticker("stocks", t)
                obs[t] = {"price": s.last_trade.p, "day_change": s.todays_change_percent}
            else:
                o = client_poly.list_snapshot_options_chain(t, limit=2)
                obs[t] = [{"strike": x.details.strike_price, "price": x.last_trade.p} for x in o]
        except: obs[t] = "N/A"
    return obs

def patrol_and_evolve():
    drones = supabase.table("drones").select("*").execute().data
    for d in drones:
        try:
            print(f"--- {d['name']} 开始巡检 ---")
            m_data = get_data(d)
            
            # 带入 Memory 进行决策
            prompt = f"""
            你是兵蜂 {d['name']}。性格：{d['persona']}。
            历史教训：{d.get('memory')}
            行情：{m_data} | 现金：{d['balance']} | 持仓：{d['positions']}
            输出JSON：{{"action":"BUY/SELL/HOLD","symbol":"...","qty":0,"price":0,"reason":"...","learning":"本次学到了什么？"}}
            """
            res = model.generate_content(prompt).text.strip()
            cmd = json.loads(res.replace("```json", "").replace("```", ""))
            
            # 更新字段
            update = {}
            if cmd['action'] == 'BUY':
                cost = cmd['qty'] * cmd['price']
                if d['balance'] >= cost:
                    update['balance'] = d['balance'] - cost
                    pos = d.get('positions', {}).copy()
                    pos[cmd['symbol']] = pos.get(cmd['symbol'], 0) + cmd['qty']
                    update['positions'] = pos
            
            update['memory'] = f"最近教训：{cmd['learning']}"
            if d['balance'] > d.get('peak_balance', 0): update['peak_balance'] = d['balance']
            
            # 日志
            new_log = {"t": datetime.now().strftime("%H:%M"), "m": cmd['reason']}
            update['logs'] = (d.get("logs", []) + [new_log])[-10:]
            
            supabase.table("drones").update(update).eq("id", d["id"]).execute()
            print(f"✅ {d['name']} 任务完成")

        except Exception as e: print(f"❌ {d['name']} 错误: {e}")

    # 简单淘汰逻辑：存活 > 12h 且 ROI < 0 且 排名末尾 30%
    # (此处可根据实际需求调用)

if __name__ == "__main__":
    patrol_and_evolve()