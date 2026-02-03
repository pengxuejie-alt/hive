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
            print(f"--- 巡检中: {d['name']} ---")
            # 1. 获取上下文（略，保持原有逻辑）
            
            # 2. 强化 Prompt：要求 AI 明确交易方向
            prompt = f"""你是兵蜂 {d['name']}。
            当前余额: ${d['balance']} | 持仓: {d.get('positions')}
            盘中状态: {"交易时间" if market_open else "休市复盘"}
            返回JSON: {{"action":"BUY/SELL/HOLD", "symbol":"...", "qty":0, "price":0, "thought":"思考", "learning":"复盘"}}"""
            
            res = model.generate_content(prompt).text.strip()
            cmd = json.loads(res.replace("```json", "").replace("```", "").strip())
            
            # 非交易时间强制设为观望，但保留思考
            final_action = cmd['action'] if market_open else "HOLD"
            
            # 3. 资产处理（增量更新）
            new_balance = float(d.get('balance', 10000.0))
            new_positions = (d.get('positions', {}) or {}).copy()
            
            if final_action == 'BUY' and market_open:
                cost = float(cmd['qty']) * float(cmd['price'])
                if new_balance >= cost:
                    new_balance -= cost
                    new_positions[cmd['symbol']] = new_positions.get(cmd['symbol'], 0) + cmd['qty']
            elif final_action == 'SELL' and market_open:
                # 卖出逻辑：检查持仓并更新余额
                if cmd['symbol'] in new_positions and new_positions[cmd['symbol']] >= cmd['qty']:
                    new_balance += float(cmd['qty']) * float(cmd['price'])
                    new_positions[cmd['symbol']] -= cmd['qty']
                    if new_positions[cmd['symbol']] <= 0: del new_positions[cmd['symbol']]

            # 4. 生成标准化流水日志
            # 格式：[时间] 方向 | 标的 | 思考 -> 决策
            timestamp = datetime.now(pytz.timezone('US/Eastern')).strftime("%m-%d %H:%M")
            action_map = {"BUY": "🟢买入", "SELL": "🔴卖出", "HOLD": "🟡观望"}
            direction = action_map.get(final_action, "❓未知")
            
            log_entry = f"[{timestamp}] {direction} | {cmd.get('symbol','--')} | 🧠 {cmd['thought']}"
            
            current_logs = d.get('logs', []) or []
            if isinstance(current_logs, str): current_logs = [current_logs]
            
            # 5. 执行更新
            update_data = {
                "balance": new_balance,
                "positions": new_positions,
                "logs": ([log_entry] + current_logs)[:20], # 滚动保留20条流水
                "memory": f"最新复盘：{cmd['learning']}",
                "peak_balance": max(float(d.get('peak_balance') or 0), new_balance)
            }
            supabase.table("drones").update(update_data).eq("id", d["id"]).execute()
            
        except Exception as e:
            print(f"❌ 错误: {e}")

if __name__ == "__main__":
    patrol_and_evolve()