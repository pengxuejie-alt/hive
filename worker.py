import os, json, pytz, sys, time
from google import genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"); sys.stdout.flush()

client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
gen_client = genai.Client(api_key=os.environ.get("GEMINI_KEY"))
MODEL_ID = "gemini-3-flash-preview"

def get_market_data_smart(tickers):
    context = {}
    now = datetime.now()
    for t in tickers:
        try:
            log(f"📡 正在构建 {t} 多维度期权菜单...")
            sn = client_poly.get_snapshot_ticker("stocks", t)
            # 兼容字段读取
            price = getattr(sn.last_trade, 'price', getattr(sn.last_trade, 'p', getattr(sn.prev_day, 'c', 0)))
            
            # 分页获取足够的数据进行本地分桶
            chain = client_poly.list_snapshot_options_chain(t, params={"limit": 150})
            buckets = {"short": [], "mid": [], "long": []}
            
            for o in chain:
                try:
                    expiry_str = o.ticker[5:11] # 提取 YYMMDD
                    expiry_dt = datetime.strptime(expiry_str, "%y%m%d")
                    days = (expiry_dt - now).days
                    o_px = getattr(o.last_trade, 'p', getattr(o.day, 'c', 0))
                    if o_px <= 0: continue

                    item = {
                        "ticker": o.ticker, "strike": o.details.strike_price,
                        "type": o.details.contract_type, "price": o_px,
                        "vol": getattr(o.day, 'v', 0), "days": days
                    }
                    # 💡 分时维度逻辑：14天/45天/180天
                    if days <= 14: buckets["short"].append(item)
                    elif 30 <= days <= 50: buckets["mid"].append(item)
                    elif days >= 150: buckets["long"].append(item)
                except: continue

            # 每个桶选成交量前 5
            final_opts = []
            for b in buckets:
                final_opts.extend(sorted(buckets[b], key=lambda x: x['vol'], reverse=True)[:5])
            
            context[t] = {"price": price, "options": final_opts}
            log(f"✅ {t} 采样完成，提供 {len(final_opts)} 个合约")
        except Exception as e:
            log(f"⚠️ {t} 采集异常: {e}")
    return context

def patrol_and_evolve():
    res = supabase.table("drones").select("*").execute()
    ts = datetime.now(pytz.timezone('US/Eastern')).strftime("%H:%M:%S")

    for d in res.data:
        try:
            log(f"--- 🐝 巡检: {d['name']} ---")
            m_data = get_market_data_smart(d.get('portfolio', ['GLD']))
            
            prompt = f"你是工蜂{d['name']}。余额:{d['balance']}。行情:{json.dumps(m_data)}。请基于短中远期权的时间价值决策。返回纯JSON: {{'trades':[], 'thought':''}}"
            
            ai_res = gen_client.models.generate_content(model=MODEL_ID, contents=prompt, config={'response_mime_type': 'application/json'})
            cmd = json.loads(ai_res.text)
            if isinstance(cmd, list): cmd = cmd[0]

            new_bal, new_pos, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            
            for t in cmd.get('trades', []):
                sym = t.get('symbol', t.get('ticker', ''))
                qty = t.get('qty', 0)
                if not sym or qty <= 0: continue
                
                # 💡 核心优化：决策时实时锁价
                log(f"🎯 正在为决策合约 {sym} 实时锁价...")
                p_obj = client_poly.get_last_trade(sym)
                current_p = getattr(p_obj, 'price', getattr(p_obj, 'p', t.get('price', 0)))
                
                mult = 100 if "O:" in sym else 1
                cost = float(qty) * float(current_p) * mult
                
                if t['action'].upper() == 'BUY' and new_bal >= cost:
                    new_bal -= cost
                    new_pos[sym] = new_pos.get(sym, 0) + qty
                    reports.append(f"🟢买入 {sym} @{current_p}")
                elif t['action'].upper() == 'SELL' and new_pos.get(sym, 0) >= qty:
                    new_bal += cost
                    new_pos[sym] -= qty
                    if new_pos[sym] <= 0: del new_pos[sym]
                    reports.append(f"🔴卖出 {sym} @{current_p}")

            # 资产重估
            mv = 0.0
            for s, q in new_pos.items():
                try:
                    p_obj = client_poly.get_last_trade(s)
                    mv += q * getattr(p_obj, 'price', 0) * (100 if "O:" in s else 1)
                except: pass

            supabase.table("drones").update({
                "balance": new_bal, "positions": new_pos, "total_assets": round(new_bal + mv, 2),
                "logs": ([f"[{ts}] {(' | '.join(reports) if reports else '🟡观望')} | 🧠 {cmd.get('thought','')}"] + (d.get('logs') or []))[:20],
                "patrol_count": (int(d.get('patrol_count') or 0)) + 1
            }).eq("id", d["id"]).execute()
            log(f"✅ {d['name']} 完毕")
        except Exception as e:
            log(f"❌ {d['name']} 异常: {e}")

if __name__ == "__main__":
    patrol_and_evolve()