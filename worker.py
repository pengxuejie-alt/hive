import os, json, pytz, sys, time
from google import genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()

log("🚀 属性适配引擎启动 (Fix: Attribute 'p')...")

try:
    client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
    supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
    gen_client = genai.Client(api_key=os.environ.get("GEMINI_KEY"))
    MODEL_ID = "gemini-3-flash-preview"
    log("✅ 客户端重连成功")
except Exception as e:
    log(f"❌ 初始化失败: {e}")
    sys.exit(1)

def get_safe_price(obj):
    """万能价格提取器：适配 .p, .price, .c 等多种返回格式"""
    if not obj: return 0
    # 依次尝试可能的属性名
    for attr in ['price', 'p', 'last', 'c', 'close']:
        val = getattr(obj, attr, 0)
        if val and val > 0: return float(val)
    return 0

def get_market_data_robust(tickers):
    context = {}
    for t in tickers:
        try:
            log(f"📡 穿透标的数据: {t}")
            # 获取 Snapshot
            sn = client_poly.get_snapshot_ticker("stocks", t)
            
            # 1. 提取股价 (多级回退)
            price = get_safe_price(sn.last_trade)
            if price == 0: price = get_safe_price(sn.prev_day)
            
            log(f"🎯 {t} 确认价格: {price}")

            # 2. 提取期权链
            log(f"⛓️ 正在扫描活跃期权链: {t}")
            options_pool = []
            chain = client_poly.list_snapshot_options_chain(
                t, params={"limit": 15, "sort": "volume", "order": "desc"}
            )
            
            for o in chain:
                # 安全获取期权价格
                o_px = get_safe_price(o.last_trade)
                if o_px == 0: o_px = get_safe_price(o.day)
                
                # 只要有价格就记录
                if o_px > 0:
                    options_pool.append({
                        "ticker": o.ticker,
                        "strike": getattr(o.details, 'strike_price', 0),
                        "type": getattr(o.details, 'contract_type', 'unknown'),
                        "price": o_px,
                        "vol": getattr(o.day, 'v', 0)
                    })
            
            context[t] = {"price": price, "options": options_pool}
            log(f"✅ {t} 数据就绪 (价格:{price}, 期权:{len(options_pool)}个)")
            
        except Exception as e:
            log(f"⚠️ {t} 采集逻辑触发异常: {e}")
            context[t] = {"price": 0, "options": []}
    return context

def patrol_and_evolve():
    res = supabase.table("drones").select("*").execute()
    drones = res.data
    ts = datetime.now(pytz.timezone('US/Eastern')).strftime("%H:%M:%S")

    for d in drones:
        try:
            log(f"--- 🐝 处理工蜂: {d['name']} ---")
            m_data = get_market_data_robust(d.get('portfolio', ['GLD']))
            
            if m_data.get('GLD', {}).get('price', 0) == 0:
                log("❗ 警告：未能获取到 GLD 有效价格，跳过此轮决策。")
                continue

            prompt = "你是工蜂{}。性格:{}。余额:{}。持仓:{}。行情:{}。返回纯JSON: {{'trades':[], 'thought':'', 'learning':''}}".format(
                d['name'], d['persona'], d['balance'], d.get('positions'), json.dumps(m_data)
            )
            
            ai_res = gen_client.models.generate_content(
                model=MODEL_ID, contents=prompt, config={'response_mime_type': 'application/json'}
            )
            cmd = json.loads(ai_res.text)
            if isinstance(cmd, list): cmd = cmd[0]

            # 交易逻辑
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

            # 重估总资产
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
            
            log(f"✨ {d['name']} 巡检完毕")
            time.sleep(1) # 保护 API

        except Exception as e:
            log(f"❌ {d['name']} 崩溃: {e}")

if __name__ == "__main__":
    patrol_and_evolve()