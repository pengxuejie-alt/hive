import os, json, pytz, sys, time
from google import genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()

log("🚀 属性精确定位引擎启动 (Fix: details.ticker)...")

try:
    client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
    supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
    gen_client = genai.Client(api_key=os.environ.get("GEMINI_KEY"))
    MODEL_ID = "gemini-3-flash-preview"
    log("✅ API 客户端就绪")
except Exception as e:
    log(f"❌ 初始化失败: {e}")
    sys.exit(1)

def get_safe_val(obj, path, default=0):
    """
    深度穿透获取属性，例如 path="details.ticker"
    """
    try:
        parts = path.split(".")
        val = obj
        for part in parts:
            val = getattr(val, part)
        return val
    except:
        return default

def get_market_data_robust(tickers):
    context = {}
    for t in tickers:
        try:
            log(f"📡 穿透标的数据: {t}")
            sn = client_poly.get_snapshot_ticker("stocks", t)
            
            # 股价提取：适配最新 SDK
            price = get_safe_val(sn, "last_trade.price")
            if price == 0: price = get_safe_val(sn, "prev_day.c")
            log(f"🎯 {t} 确认价格: {price}")

            log(f"⛓️ 扫描期权链: {t}")
            all_options = []
            chain = client_poly.list_snapshot_options_chain(t, params={"limit": 50})
            
            for o in chain:
                # 修复核心：期权代码在 details.ticker 
                o_ticker = get_safe_val(o, "details.ticker", "")
                o_px = get_safe_val(o, "last_trade.price")
                if o_px == 0: o_px = get_safe_val(o, "day.c")
                
                if o_ticker and o_px > 0:
                    all_options.append({
                        "ticker": o_ticker,
                        "strike": get_safe_val(o, "details.strike_price"),
                        "type": get_safe_val(o, "details.contract_type", "unknown"),
                        "price": o_px,
                        "vol": get_safe_val(o, "day.v")
                    })
            
            # 本地按成交量排序
            sorted_options = sorted(all_options, key=lambda x: x['vol'], reverse=True)[:15]
            
            context[t] = {"price": price, "options": sorted_options}
            log(f"✅ {t} 数据就绪 (价格:{price}, 期权数:{len(sorted_options)})")
            
        except Exception as e:
            log(f"⚠️ {t} 数据采集部分受阻: {e}")
            # 注意：即便期权链报错，只要拿到了 price 就不应该让 context[t] 整体失效
            if 'price' not in locals() or price == 0:
                context[t] = {"price": 0, "options": []}
            else:
                context[t] = {"price": price, "options": []}
    return context

def patrol_and_evolve():
    res = supabase.table("drones").select("*").execute()
    drones = res.data
    ts = datetime.now(pytz.timezone('US/Eastern')).strftime("%H:%M:%S")

    for d in drones:
        try:
            log(f"--- 🐝 处理工蜂: {d['name']} ---")
            m_data = get_market_data_robust(d.get('portfolio', ['GLD']))
            
            # 获取标的价格，判断是否跳过决策
            gld_info = m_data.get('GLD', m_data.get(next(iter(m_data)) if m_data else {}, {}))
            if gld_info.get('price', 0) == 0:
                log(f"❗ 错误：无法获取有效价格，跳过 {d['name']}")
                continue

            prompt = "你是工蜂{}。性格:{}。余额:{}。持仓:{}。行情:{}。返回纯JSON: {{'trades':[], 'thought':'', 'learning':''}}".format(
                d['name'], d['persona'], d['balance'], d.get('positions'), json.dumps(m_data)
            )
            
            ai_res = gen_client.models.generate_content(
                model=MODEL_ID, contents=prompt, config={'response_mime_type': 'application/json'}
            )
            cmd = json.loads(ai_res.text)
            if isinstance(cmd, list): cmd = cmd[0]

            new_bal, new_pos, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            trades = cmd.get('trades', []) if isinstance(cmd, dict) else []
            
            for t in trades:
                sym, mult = t['symbol'], (100 if t['symbol'].startswith("O:") else 1)
                cost = float(t['qty']) * float(t['price']) * mult
                if t['action'] == 'BUY' and new_bal >= cost:
                    new_bal -= cost
                    new_pos[sym] = new_pos.get(sym, 0) + t['qty']
                    reports.append("🟢买入 {}".format(sym))
                elif t['action'] == 'SELL' and new_pos.get(sym, 0) >= t['qty']:
                    new_bal += cost
                    new_pos[sym] -= t['qty']
                    if new_pos[sym] <= 0: del new_pos[sym]
                    reports.append("🔴卖出 {}".format(sym))

            # 资产重估
            mv = 0.0
            for s, q in new_pos.items():
                try:
                    lp_obj = client_poly.get_last_trade(s)
                    lp = getattr(lp_obj, 'price', getattr(lp_obj, 'p', 0))
                    mv += q * lp * (100 if s.startswith("O:") else 1)
                except: pass

            log_str = "[{}] {} | 🧠 {}".format(ts, " | ".join(reports) if reports else "🟡观望", cmd.get('thought', '...'))
            supabase.table("drones").update({
                "balance": new_bal, "positions": new_pos, "total_assets": round(new_bal + mv, 2),
                "logs": ([log_str] + (d.get('logs') or []))[:20],
                "patrol_count": (int(d.get('patrol_count') or 0)) + 1,
                "memory": cmd.get('learning', '')
            }).eq("id", d["id"]).execute()
            
            log(f"✅ {d['name']} 巡检完毕")
            time.sleep(1)

        except Exception as e:
            log(f"❌ {d['name']} 崩溃: {e}")

if __name__ == "__main__":
    patrol_and_evolve()