import os
import json
import google.generativeai as genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

# --- 配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel(AI_MODEL_NAME)

def get_data(d):
    obs = {}
    for t in d["portfolio"]:
        try:
            if d['focus'] == 'stock':
                s = client_poly.get_snapshot_ticker("stocks", t)
                obs[t] = {"price": s.last_trade.p, "day_change": s.todays_change_percent}
            else:
                o = client_poly.list_snapshot_options_chain(t, limit=2)
                obs[t] = [{"strike": x.details.strike_price, "price": x.last_trade.p, "type": x.details.contract_type} for x in o]
        except: obs[t] = "N/A"
    return obs

def run_patrol():
    drones = supabase.table("drones").select("*").execute().data
    for d in drones:
        try:
            data = get_data(d)
            start_time = datetime.fromisoformat(d['created_at'].replace('Z', '+00:00'))
            age_hrs = (datetime.now(timezone.utc) - start_time).total_seconds() / 3600
            
            if d['type'] == 'soldier':
                prompt = f"""
                你是兵蜂 {d['name']} ({d['persona']})。
                已生存: {age_hrs:.1f} 小时。
                可用现金: ${d['balance']} | 持仓: {d['positions']}
                实时行情: {data}
                
                输出JSON执行指令：{{"action": "BUY/SELL/HOLD", "symbol": "代码", "qty": 数量, "price": 价格, "reason": "理由"}}
                """
            else:
                prompt = f"工蜂 {d['name']} 分析行情。逻辑: {d['logic']}。数据: {data}。给出100字内分析。"

            res = model.generate_content(prompt).text.strip()
            clean = res.replace("```json", "").replace("```", "").strip()

            update_data = {}
            if d['type'] == 'soldier':
                cmd = json.loads(clean)
                log_msg = f"{cmd['action']} {cmd['qty']} {cmd['symbol']}: {cmd['reason']}"
                # 模拟简单的买入扣款逻辑
                if cmd['action'] == 'BUY':
                    cost = cmd['qty'] * cmd['price']
                    if d['balance'] >= cost:
                        update_data['balance'] = d['balance'] - cost
                        new_pos = d['positions'].copy()
                        new_pos[cmd['symbol']] = new_pos.get(cmd['symbol'], 0) + cmd['qty']
                        update_data['positions'] = new_pos
            else:
                log_msg = clean[:150]

            # 更新数据库
            new_log = {"t": datetime.now().strftime("%H:%M"), "m": log_msg}
            update_data['logs'] = (d.get("logs", []) + [new_log])[-10:]
            supabase.table("drones").update(update_data).eq("id", d["id"]).execute()
            print(f"✅ {d['name']} 已更新")

        except Exception as e: print(f"❌ {d['name']} 报错: {e}")

if __name__ == "__main__":
    run_patrol()