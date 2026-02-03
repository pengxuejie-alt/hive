import os, json, pytz, sys, time
from google import genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()

log("🚀 蜂巢巡检系统 - 鲁棒性加固版启动...")

try:
    client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
    supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
    gen_client = genai.Client(api_key=os.environ.get("GEMINI_KEY"))
    MODEL_ID = "gemini-3-flash-preview"
    log("✅ 链路已建立")
except Exception as e:
    log(f"❌ 初始化失败: {e}")
    sys.exit(1)

def get_safe_val(obj, path, default=0):
    try:
        parts = path.split(".")
        val = obj
        for part in parts:
            val = getattr(val, part)
        return val if val is not None else default
    except:
        return default

def get_market_data_robust(tickers):
    context = {}
    for t in tickers:
        try:
            log(f"📡 穿透标的数据: {t}")
            sn = client_poly.get_snapshot_ticker("stocks", t)
            price = get_safe_val(sn, "last_trade.price", 0)
            if price == 0: price = get_safe_val(sn, "prev_day.c", 0)
            log(f"🎯 {t} 确认价格: {price}")

            log(f"⛓️ 扫描期权链: {t}")
            all_options = []
            chain = client_poly.list_snapshot_options_chain(t, params={"limit": 30})
            
            for o in chain:
                o_ticker = get_safe_val(o, "details.ticker", "")
                o_px = get_safe_val(o, "last_trade.price", 0)
                if o_px == 0: o_px = get_safe_val(o, "day.c", 0)
                # 核心修复：确保成交量不为 None 
                o_vol = get_safe_val(o, "day.v", 0) 
                
                if o_ticker and o_px > 0:
                    all_options.append({
                        "ticker": o_ticker,
                        "strike": get_safe_val(o, "details.strike_price"),
                        "type": get_safe_val(o, "details.contract_type", "unknown"),
                        "price": o_px,
                        "vol": o_vol
                    })
            
            # 排序容错：所有 vol 此时均为数字
            sorted_options = sorted(all_options, key=lambda x: x['vol'], reverse=True)[:15]
            context[t] = {"price": price, "options": sorted_options}
            log(f"✅ {t} 数据就绪 (期权数:{len(sorted_options)})")
            
        except Exception as e:
            log(f"⚠️ {t} 采集受损: {e}")
            context[t] = {"price": locals().get('price', 0), "options": []}
    return context

def patrol_and_evolve():
    d_res = supabase.table("drones").select("*").execute()
    ts = datetime.now(pytz.timezone('US/Eastern')).strftime("%H:%M:%S")

    for d in d_res.data:
        try:
            log(f"--- 🐝 处理工蜂: {d['name']} ---")
            m_data = get_market_data_robust(d.get('portfolio', ['GLD']))
            
            if m_data.get('GLD', {}).get('price', 0) == 0: continue

            prompt = f"工蜂{d['name']}。余额:{d['balance']}。行情:{json.dumps(m_data)}。返回JSON: {{'trades':[], 'thought':'', 'learning':''}}"
            
            ai_res = gen_client.models.generate_content(model=MODEL_ID, contents=prompt, config={'response_mime_type': 'application/json'})
            cmd = json.loads(ai_res.text)
            if isinstance(cmd, list): cmd = cmd[0]

            new_bal, new_pos, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            
            # 核心修复：对交易指令字段进行模糊匹配
            trades = cmd.get('trades', [])
            for t in trades:
                # 兼容 qty/quantity, symbol/ticker, price/px
                q = t.get('qty', t.get('quantity', 0))
                s = t.get('symbol', t.get('ticker', ''))
                p = t.get('price', t.get('px', 0))
                a = t.get('action', '').upper()
                
                if not s or q <= 0 or p <= 0: continue
                
                mult = 100 if s.startswith("O:") else 1
                cost = float(q) * float(p) * mult
                
                if a == 'BUY' and new_bal >= cost:
                    new_bal -= cost
                    new_pos[s] = new_pos.get(s, 0) + q
                    reports.append(f"🟢买入 {s}")
                elif a == 'SELL' and new_pos.get(s, 0) >= q:
                    new_bal += cost
                    new_pos[s] -= q
                    if new_pos[s] <= 0: del new_pos[s]
                    reports.append(f"🔴卖出 {s}")

            # 市值重估逻辑优化
            mv = 0.0
            for s, q in new_pos.items():
                try:
                    p_obj = client_poly.get_last_trade(s)
                    lp = getattr(p_obj, 'price', getattr(p_obj, 'p', 0))
                    mv += q * (lp if lp else 0) * (100 if s.startswith("O:") else 1)
                except: pass

            log_str = "[{}] {} | 🧠 {}".format(ts, " | ".join(reports) if reports else "🟡观望", cmd.get('thought', '...'))
            supabase.table("drones").update({
                "balance": new_bal, "positions": new_pos, "total_assets": round(new_bal + mv, 2),
                "logs": ([log_str] + (d.get('logs') or []))[:20],
                "patrol_count": (int(d.get('patrol_count') or 0)) + 1,
                "memory": cmd.get('learning', '')
            }).eq("id", d["id"]).execute()
            
            log(f"✅ {d['name']} 演化成功")
            time.sleep(1)
        except Exception as e:
            log(f"❌ {d['name']} 崩溃: {e}")

if __name__ == "__main__":
    patrol_and_evolve()