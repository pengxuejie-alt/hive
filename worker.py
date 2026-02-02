import os, json, pytz
import google.generativeai as genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime

# --- 初始化 ---
client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel("gemini-3-flash-preview")

def is_market_open():
    et_tz = pytz.timezone('US/Eastern')
    now = datetime.now(et_tz)
    if now.weekday() >= 5: return False
    start = now.replace(hour=9, minute=30, second=0)
    end = now.replace(hour=16, minute=0, second=0)
    return start <= now <= end

def patrol_and_evolve():
    market_open = is_market_open()
    drones = supabase.table("drones").select("*").execute().data
    for d in drones:
        try:
            print(f"--- {d['name']} 巡检开始 ---")
            m_data = {} # 这里补充 fetch_data 逻辑
            
            restriction = "" if market_open else "【非交易时段：仅限观察与 HOLD】"
            prompt = f"你是兵蜂 {d['name']}。{restriction} 历史经验: {d.get('memory')}。行情: {m_data}。输出纯JSON: {{'action':'BUY/SELL/HOLD', 'symbol':'...', 'qty':0, 'price':0, 'reason':'...', 'learning':'心得'}}"
            
            res = model.generate_content(prompt).text.strip()
            cmd = json.loads(res.replace("```json", "").replace("```", "").strip())
            
            if not market_open: cmd['action'] = 'HOLD'
            
            # --- 账本更新 ---
            update = {}
            if cmd['action'] == 'BUY':
                cost = cmd['qty'] * cmd['price']
                if d['balance'] >= cost:
                    update['balance'] = float(d['balance']) - cost
                    pos = d.get('positions', {}).copy()
                    pos[cmd['symbol']] = pos.get(cmd['symbol'], 0) + cmd['qty']
                    update['positions'] = pos
            
            # 记录经验与峰值，确保没有 None
            update['memory'] = f"最新记录：{cmd['learning']}"
            current_bal = float(update.get('balance', d['balance']))
            update['peak_balance'] = max(float(d.get('peak_balance') or 0), current_bal, 1.0)
            
            supabase.table("drones").update(update).eq("id", d["id"]).execute()
            print(f"✅ {d['name']} 完成")
        except Exception as e: 
            print(f"❌ {d['name']} 异常: {e}")

if __name__ == "__main__":
    patrol_and_evolve()