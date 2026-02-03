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
    start, end = now.replace(hour=9, minute=30, second=0), now.replace(hour=16, minute=0, second=0)
    return start <= now <= end

def patrol_and_evolve():
    market_open = is_market_open()
    drones = supabase.table("drones").select("*").execute().data
    for d in drones:
        try:
            print(f"--- {d['name']} 巡检 ---")
            m_data = {"current_time_et": datetime.now(pytz.timezone('US/Eastern')).strftime("%H:%M:%S")}
            
            restriction = "" if market_open else "【非交易时段：禁止 BUY/SELL。请分析行情，在 reason 中描述如果你在盘中会做什么交易，并在 learning 中复盘策略。】"
            
            prompt = f"""你是兵蜂 {d['name']}。基因策略：{d['logic']} ({d['persona']})。
            往期经验：{d.get('memory')}
            账户：${d['balance']} | 标的：{d['portfolio']} | 行情摘要：{m_data}
            {restriction}
            请决策并深度复盘。返回纯JSON：{{"action":"BUY/SELL/HOLD","symbol":"...","qty":0,"price":0,"reason":"思考过程","learning":"策略复盘"}}"""
            
            res = model.generate_content(prompt).text.strip()
            cmd = json.loads(res.replace("```json", "").replace("```", "").strip())
            
            # 物理锁定
            if not market_open: cmd['action'] = 'HOLD'
            
            update = {}
            # 日志更新
            new_log = {"time": datetime.now().strftime("%m-%d %H:%M"), "thought": cmd['reason'], "action": cmd['action']}
            update['logs'] = ([new_log] + (d.get('logs') or []))[:10]
            
            if market_open and cmd['action'] == 'BUY':
                cost = cmd['qty'] * cmd['price']
                if d['balance'] >= cost:
                    update['balance'] = float(d['balance']) - cost
                    pos = d.get('positions', {}).copy(); pos[cmd['symbol']] = pos.get(cmd['symbol'], 0) + cmd['qty']
                    update['positions'] = pos

            update['memory'] = f"【后天复盘】: {cmd['learning']}"
            update['peak_balance'] = max(float(d.get('peak_balance') or 0), float(update.get('balance', d['balance'])), 1.0)
            
            supabase.table("drones").update(update).eq("id", d["id"]).execute()
            print(f"✅ {d['name']} 复盘更新完成")
        except Exception as e: print(f"❌ {d['name']} 异常: {e}")

if __name__ == "__main__":
    patrol_and_evolve()