import os, json, pytz, sys, time
from google import genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()

log("🚀 巡检引擎启动 (增强防御版)...")

try:
    client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
    supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
    gen_client = genai.Client(api_key=os.environ.get("GEMINI_KEY"))
    MODEL_ID = "gemini-3-flash-preview"
    log(f"✅ 核心组件就绪: {MODEL_ID}")
except Exception as e:
    log(f"❌ 初始化失败: {e}")
    sys.exit(1)

def get_market_data_fast(tickers):
    context = {}
    for t in tickers:
        try:
            time.sleep(0.5) # 💡 增加 0.5 秒延迟，防止 Polygon 并发报错
            log(f"🔍 穿透价格: {t}")
            lt = client_poly.get_last_trade(t)
            price = lt.price if lt and lt.price > 0 else 0
            
            log(f"🔍 过滤活跃期权: {t}")
            options_pool = []
            chain = client_poly.list_snapshot_options_chain(t, params={"limit": 10, "sort": "volume", "order": "desc"})
            
            for o in chain:
                if getattr(o.day, 'v', 0) > 0 and o.last_trade.p > 0:
                    options_pool.append({"ticker": o.ticker, "price": o.last_trade.p})
            context[t] = {"price": price, "options": options_pool}
        except Exception as e:
            log(f"⚠️ {t} 数据采集受阻，使用空行情进入决策")
            context[t] = {"price": 0, "options": []}
    return context

def patrol_and_evolve():
    d_res = supabase.table("drones").select("*").execute()
    drones = d_res.data
    ts = datetime.now(pytz.timezone('US/Eastern')).strftime("%H:%M:%S")

    for d in drones:
        try:
            log(f"--- 🐝 巡检: {d['name']} ---")
            m_data = get_market_data_fast(d.get('portfolio', ['GLD']))
            
            log(f"🧠 调用演化脑...")
            prompt = "工蜂{}。余额:{}。持仓:{}。行情:{}。决策JSON: {{'trades':[], 'thought':'', 'learning':''}}".format(
                d['name'], d['balance'], d.get('positions'), json.dumps(m_data)
            )
            
            res = gen_client.models.generate_content(
                model=MODEL_ID, contents=prompt,
                config={'response_mime_type': 'application/json'}
            )
            
            # 💡 容错修复 1: 确保 AI 返回的是字典
            cmd = json.loads(res.text)
            if isinstance(cmd, list): 
                log("⚠️ AI 返回了列表格式，正在强制纠正为字典...")
                cmd = cmd[0] if len(cmd) > 0 else {"trades": [], "thought": "格式异常纠正", "learning": ""}

            new_bal, new_pos, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            
            # 💡 容错修复 2: 严格检查 trades 键
            trades = cmd.get('trades', []) if isinstance(cmd, dict) else []
            for t in trades:
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

            log("💰 计算持仓现值...")
            mv = 0.0
            for s, q in new_pos.items():
                try:
                    p = client_poly.get_last_trade(s).price if s.startswith("O:") else client_poly.get_snapshot_ticker("stocks", s).last_trade.p
                    mv += q * p * (100 if s.startswith("O:") else 1)
                except: pass

            log("💾 同步数据库...")
            thought = cmd.get('thought', '思考中') if isinstance(cmd, dict) else '格式异常'
            log_str = "[{}] {} | 🧠 {}".format(ts, " | ".join(reports) if reports else "🟡观望", thought)
            
            supabase.table("drones").update({
                "balance": new_bal, "positions": new_pos, "total_assets": round(new_bal + mv, 2),
                "logs": ([log_str] + (d.get('logs') or []))[:20],
                "patrol_count": (int(d.get('patrol_count') or 0)) + 1,
                "memory": cmd.get('learning', '')
            }).eq("id", d["id"]).execute()
            
            log(f"✅ {d['name']} 演化成功")
        except Exception as e:
            log(f"❌ {d['name']} 异常: {e}")

if __name__ == "__main__":
    patrol_and_evolve()
    log("🏁 巡检全流程结束")