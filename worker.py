import os, json
import google.generativeai as genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

# --- 初始化 ---
client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel("gemini-3-flash-preview")

def get_market_data(d):
    obs = {}
    for t in d["portfolio"]:
        try:
            if d['focus'] == 'stock':
                s = client_poly.get_snapshot_ticker("stocks", t)
                obs[t] = {"price": s.last_trade.p, "change": s.todays_change_percent}
            else:
                o = client_poly.list_snapshot_options_chain(t, limit=3)
                obs[t] = [{"strike": x.details.strike_price, "price": x.last_trade.p, "type": x.details.contract_type} for x in o]
        except: obs[t] = "N/A"
    return obs

def patrol_and_evolve():
    drones = supabase.table("drones").select("*").execute().data
    for d in drones:
        try:
            print(f"--- {d['name']} 正在巡检 ---")
            m_data = get_market_data(d)
            
            # 强化 Prompt 以抑制无脑满仓倾向
            prompt = f"""
            你是兵蜂 {d['name']}。性格：{d['persona']}。
            当前余额: ${d['balance']} | 持仓: {d['positions']}
            行情数据: {m_data}
            历史教训: {d.get('memory')}
            
            要求：
            1. 决定 [BUY/SELL/HOLD]。
            2. 严禁无脑满仓。请根据信心水平合理分配可用现金。
            3. 如果是期权，注意时间价值衰减，选择合适的执行价。
            4. 写下本次操作的教训(learning)。
            
            输出纯JSON：{{"action":"BUY/SELL/HOLD","symbol":"...","qty":0,"price":0,"reason":"...","learning":"..."}}
            """
            res = model.generate_content(prompt).text.strip()
            cmd = json.loads(res.replace("```json", "").replace("```", ""))
            
            update = {}
            if cmd['action'] == 'BUY':
                cost = cmd['qty'] * cmd['price']
                if d['balance'] >= cost:
                    update['balance'] = d['balance'] - cost
                    new_pos = d.get('positions', {}).copy()
                    new_pos[cmd['symbol']] = new_pos.get(cmd['symbol'], 0) + cmd['qty']
                    update['positions'] = new_pos
            
            # 记录资产峰值与学习心得
            update['memory'] = f"上次学习：{cmd['learning']}"
            current_bal = update.get('balance', d['balance'])
            update['peak_balance'] = max(d.get('peak_balance', 0), current_bal, 1)
            
            new_log = {"t": datetime.now().strftime("%H:%M"), "m": cmd['reason']}
            update['logs'] = (d.get("logs", []) + [new_log])[-10:]
            
            supabase.table("drones").update(update).eq("id", d["id"]).execute()
            print(f"✅ {d['name']} 任务完成")

        except Exception as e: print(f"❌ {d['name']} 错误: {e}")

if __name__ == "__main__":
    patrol_and_evolve()