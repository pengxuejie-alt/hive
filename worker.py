import os, json, pytz
import google.generativeai as genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

# --- 初始化 ---
client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel("gemini-3-flash-preview")

def get_market_data(tickers):
    context = {}
    for t in tickers:
        try:
            snap = client_poly.get_snapshot_ticker("stocks", t)
            price = snap.last_trade.p if snap.last_trade else snap.prev_day.c
            chain = client_poly.list_snapshot_options_chain(t, params={"limit": 10})
            options = [{"ticker": o.ticker, "price": o.last_trade.p, "type": o.details.contract_type} for o in chain]
            context[t] = {"stock_price": price, "options": options}
        except: pass
    return context

def patrol_and_evolve():
    drones = supabase.table("drones").select("*").execute().data
    ts = datetime.now(pytz.timezone('US/Eastern')).strftime("%m-%d %H:%M")

    for d in drones:
        try:
            m_data = get_market_data(d.get('portfolio', ['AMD']))
            prompt = f"你是工蜂{d['name']}。性格:{d['persona']}。余额:${d['balance']}。持仓:{d.get('positions')}。行情:{json.dumps(m_data)}。请决策并返回JSON: {{'trades':[], 'thought':'', 'learning':''}}"
            
            res_ai = model.generate_content(prompt).text.strip()
            cmd = json.loads(res_ai.replace("```json", "").replace("```", "").strip())
            
            # 交易逻辑与资产保全
            new_bal, new_pos, logs = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            for t in cmd.get('trades', []):
                mult = 100 if "O:" in t['symbol'] else 1
                cost = t['qty'] * t['price'] * mult
                if t['action'] == 'BUY' and new_bal >= cost:
                    new_bal -= cost
                    new_pos[t['symbol']] = new_pos.get(t['symbol'], 0) + t['qty']
                    logs.append(f"🟢买入 {t['symbol']} x{t['qty']}")
            
            # 核心：计算并存入 total_assets 字段
            mkt_val = 0.0
            for s, q in new_pos.items():
                try:
                    # 使用当前巡检到的最新价格
                    price = poly_client.get_last_trade(s).price if "O:" in s else client_poly.get_snapshot_ticker("stocks", s).last_trade.p
                    mkt_val += q * price * (100 if "O:" in s else 1)
                except: pass

            update = {
                "balance": new_bal, "positions": new_pos, "total_assets": new_bal + mkt_val,
                "logs": ([f"[{ts}] {' | '.join(logs) or '🟡保持不动'} | 🧠 {cmd['thought']}"] + (d.get('logs') or []))[:15],
                "patrol_count": (d.get('patrol_count', 0) or 0) + 1,
                "memory": cmd['learning']
            }
            supabase.table("drones").update(update).eq("id", d["id"]).execute()
        except Exception as e: print(f"Error {d['name']}: {e}")

if __name__ == "__main__":
    patrol_and_evolve()