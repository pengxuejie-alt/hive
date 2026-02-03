import os, json, pytz
from google import genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
gen_client = genai.Client(api_key=os.environ.get("GEMINI_KEY"))
MODEL_ID = "gemini-2.0-flash-exp"

def get_market_data(tickers):
    context = {}
    for t in tickers:
        try:
            lt = client_poly.get_last_trade(t)
            price = lt.price if lt and lt.price > 0 else client_poly.get_snapshot_ticker("stocks", t).prev_day.c
            chain = client_poly.list_snapshot_options_chain(t, params={"limit": 10})
            opts = [{"ticker": o.ticker, "price": o.last_trade.p, "vol": o.day.v} for o in chain if getattr(o.day, 'v', 0) > 0]
            context[t] = {"price": price, "options": opts}
        except: pass
    return context

def patrol_and_evolve():
    drones = supabase.table("drones").select("*").execute().data
    ts = datetime.now(pytz.timezone('US/Eastern')).strftime("%H:%M:%S")

    for d in drones:
        try:
            print("--- 🐝 巡检: {} ---".format(d['name']))
            m_data = get_market_data(d.get('portfolio', ['GLD']))
            prompt = "你是工蜂{}。性格:{}。余额:{}。行情:{}。决策交易返回JSON: {{'trades':[], 'thought':'', 'learning':''}}".format(
                d['name'], d['persona'], d['balance'], json.dumps(m_data)
            )
            
            res = gen_client.models.generate_content(model=MODEL_ID, contents=prompt, config={'response_mime_type': 'application/json'})
            cmd = json.loads(res.text)

            new_bal, new_pos, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            for t in cmd.get('trades', []):
                sym, mult = t['symbol'], (100 if t['symbol'].startswith("O:") else 1)
                cost = t['qty'] * t['price'] * mult
                if t['action'] == 'BUY' and new_bal >= cost:
                    new_bal -= cost
                    new_pos[sym] = new_pos.get(sym, 0) + t['qty']
                    reports.append("🟢买入 {}".format(sym))
                elif t['action'] == 'SELL' and new_pos.get(sym, 0) >= t['qty']:
                    new_bal += cost
                    new_pos[sym] -= t['qty']
                    if new_pos[sym] <= 0: del new_pos[sym]
                    reports.append("🔴卖出 {}".format(sym))

            mv = 0.0
            for s, q in new_pos.items():
                try:
                    p = client_poly.get_last_trade(s).price if s.startswith("O:") else client_poly.get_snapshot_ticker("stocks", s).last_trade.p
                    mv += q * p * (100 if s.startswith("O:") else 1)
                except: pass

            log_str = "[{}] {} | 🧠 {}".format(ts, " | ".join(reports) if reports else "🟡观望", cmd['thought'])
            
            supabase.table("drones").update({
                "balance": new_bal, "positions": new_pos, "total_assets": round(new_bal + mv, 2),
                "logs": ([log_str] + (d.get('logs') or []))[:20],
                "patrol_count": (int(d.get('patrol_count') or 0)) + 1,
                "memory": cmd['learning']
            }).eq("id", d["id"]).execute()
            print("✅ {} 完毕".format(d['name']))
        except Exception as e:
            print("❌ {} 崩溃: {}".format(d.get('name'), str(e)))

if __name__ == "__main__":
    patrol_and_evolve()