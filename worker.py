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
                o = client_poly.list_snapshot_options_chain(t, limit=2)
                obs[t] = [{"strike": x.details.strike_price, "price": x.last_trade.p} for x in o]
        except: obs[t] = "N/A"
    return obs

def patrol_and_evolve():
    res = supabase.table("drones").select("*").execute()
    drones = res.data
    
    for d in drones:
        try:
            # 1. 决策阶段：带入 Memory
            m_data = get_market_data(d)
            prompt = f"""
            你是兵蜂 {d['name']}。性格：{d['persona']}。
            历史教训：{d.get('memory')}
            持仓：{d['positions']} | 现金：{d['balance']}
            实时行情：{m_data}
            请决策并写下本次学到的教训(learning)。
            返回JSON：{{"action":"BUY/SELL/HOLD","symbol":"...","qty":0,"price":0,"reason":"...","learning":"..."}}
            """
            response = model.generate_content(prompt).text.strip()
            decision = json.loads(response.replace("```json", "").replace("```", ""))
            
            # 2. 模拟执行
            update_fields = {}
            if decision['action'] == 'BUY':
                cost = decision['qty'] * decision['price']
                if d['balance'] >= cost:
                    update_fields['balance'] = d['balance'] - cost
                    new_pos = d.get('positions', {}).copy()
                    new_pos[decision['symbol']] = new_pos.get(decision['symbol'], 0) + decision['qty']
                    update_fields['positions'] = new_pos
            
            # 3. 经验积累与峰值记录
            update_fields['memory'] = f"上一次学习：{decision['learning']}"
            if d['balance'] > d.get('peak_balance', 0):
                update_fields['peak_balance'] = d['balance']
                
            # 4. 更新数据库
            new_log = {"t": datetime.now().strftime("%H:%M"), "msg": decision['reason']}
            update_fields['logs'] = (d.get("logs", []) + [new_log])[-10:]
            supabase.table("drones").update(update_fields).eq("id", d["id"]).execute()
            print(f"✅ {d['name']} 任务完成并已学习。")

        except Exception as e: print(f"❌ {d['name']} 出错: {e}")

    # 5. 物竞天择 (淘汰存活 > 12h 且 ROI < 0 的末位)
    # ... 此处可复用之前提到的 natural_selection 逻辑

if __name__ == "__main__":
    patrol_and_evolve()