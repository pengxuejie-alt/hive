import os, json, pytz, sys, time
from google import genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()

log("🚀 极速兼容引擎启动 (Fix: Sort Parameter)...")

try:
    client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
    supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
    gen_client = genai.Client(api_key=os.environ.get("GEMINI_KEY"))
    MODEL_ID = "gemini-3-flash-preview"
    log("✅ 客户端初始化就绪")
except Exception as e:
    log(f"❌ 初始化失败: {e}")
    sys.exit(1)

def get_safe_price(obj):
    if not obj: return 0
    for attr in ['price', 'p', 'last', 'c', 'close']:
        val = getattr(obj, attr, 0)
        if val and val > 0: return float(val)
    return 0

def get_market_data_compatible(tickers):
    context = {}
    for t in tickers:
        try:
            log(f"📡 穿透标的数据: {t}")
            sn = client_poly.get_snapshot_ticker("stocks", t)
            price = get_safe_price(sn.last_trade)
            if price == 0: price = get_safe_price(sn.prev_day)
            
            log(f"🎯 {t} 确认价格: {price}")

            # --- 修复核心：去掉 API 端的 sort 参数，改为本地排序 ---
            log(f"⛓️ 正在扫描活跃期权链: {t}")
            all_options = []
            # 只限制 limit，不传 sort，防止 API 报错
            chain = client_poly.list_snapshot_options_chain(t, params={"limit": 50})
            
            for o in chain:
                o_px = get_safe_price(o.last_trade)
                if o_px == 0: o_px = get_safe_price(o.day)
                
                if o_px > 0:
                    all_options.append({
                        "ticker": o.ticker,
                        "strike": getattr(o.details, 'strike_price', 0),
                        "type": getattr(o.details, 'contract_type', 'unknown'),
                        "price": o_px,
                        "vol": getattr(o.day, 'v', 0)
                    })
            
            # 在 Python 本地按成交量排序，取前 15 个给 AI
            sorted_options = sorted(all_options, key=lambda x: x['vol'], reverse=True)[:15]
            
            context[t] = {"price": price, "options": sorted_options}
            log(f"✅ {t} 数据就绪 (价格:{price}, 期权:{len(sorted_options)}个)")
            
        except Exception as e:
            log(f"⚠️ {t} 采集异常: {e}")
            context[t] = {"price": 0, "options": []}
    return context

def patrol_and_evolve():
    res = supabase.table("drones").select("*").execute()
    drones = res.data
    ts = datetime.now(pytz.timezone('US/Eastern')).strftime("%H:%M:%S")

    for d in drones:
        try:
            log(f"--- 🐝 处理工蜂: {d['name']} ---")
            m_data = get_market_data_compatible(d.get('portfolio', ['GLD']))
            
            # 只有当真的没拿到价格时才跳过
            gld_p = m_data.get('GLD', {}).get('price', 0)
            if gld_p == 0:
                log(f"❗ 警告：无法获取 {d['name']} 的标的价格，跳过。")
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
                    lp = get_safe_price(client_poly.get_last_trade(s))
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