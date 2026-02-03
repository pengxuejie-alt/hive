import os, json, pytz, sys
from google import genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

# 强制实时输出日志，防止 GitHub Actions 缓存输出导致你以为卡住了
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()

log("🚀 脚本启动...")

try:
    client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
    supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
    gen_client = genai.Client(api_key=os.environ.get("GEMINI_KEY"))
    MODEL_ID = "gemini-2.0-flash-exp"
    log("✅ API 客户端初始化完成")
except Exception as e:
    log(f"❌ 初始化失败: {e}")
    sys.exit(1)

def get_market_data(tickers):
    context = {}
    for t in tickers:
        try:
            log(f"🔍 正在扫描行情: {t}")
            lt = client_poly.get_last_trade(t)
            price = lt.price if lt and lt.price > 0 else 0
            
            # 缩小扫描范围，防止 Polygon 接口超时
            log(f"🔍 正在获取期权快照: {t}")
            chain = client_poly.list_snapshot_options_chain(t, params={"limit": 8})
            opts = [{"ticker": o.ticker, "price": o.last_trade.p} for o in chain if getattr(o.day, 'v', 0) > 0]
            context[t] = {"price": price, "options": opts}
        except Exception as e:
            log(f"⚠️ {t} 行情获取异常: {e}")
    return context

def patrol_and_evolve():
    log("📡 正在从 Supabase 读取工蜂列表...")
    d_res = supabase.table("drones").select("*").execute()
    drones = d_res.data
    log(f"👯 发现 {len(drones)} 只工蜂，准备开始巡检")

    ts = datetime.now(pytz.timezone('US/Eastern')).strftime("%H:%M:%S")

    for d in drones:
        try:
            log(f"--- 🐝 开始处理: {d['name']} ---")
            
            portfolio = d.get('portfolio', ['GLD'])
            m_data = get_market_data(portfolio)
            
            log(f"🧠 正在调用 Gemini 进行演化决策 ({MODEL_ID})...")
            prompt = f"工蜂{d['name']}。余额:{d['balance']}。行情:{json.dumps(m_data)}。决策JSON: {{'trades':[], 'thought':'', 'learning':''}}"
            
            # 增加 API 调用提示
            res = gen_client.models.generate_content(
                model=MODEL_ID, 
                contents=prompt, 
                config={'response_mime_type': 'application/json'}
            )
            log(f"✅ Gemini 响应成功")
            
            cmd = json.loads(res.text)

            # 交易与资产计算逻辑
            new_bal, new_pos, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            for t in cmd.get('trades', []):
                sym, mult = t['symbol'], (100 if t['symbol'].startswith("O:") else 1)
                cost = t['qty'] * t['price'] * mult
                if t['action'] == 'BUY' and new_bal >= cost:
                    new_bal -= cost
                    new_pos[sym] = new_pos.get(sym, 0) + t['qty']
                    reports.append(f"🟢买入 {sym}")
                elif t['action'] == 'SELL' and new_pos.get(sym, 0) >= t['qty']:
                    new_bal += cost
                    new_pos[sym] -= t['qty']
                    if new_pos[sym] <= 0: del new_pos[sym]
                    reports.append(f"🔴卖出 {sym}")

            log("💰 正在计算实时持仓市值...")
            mv = 0.0
            for s, q in new_pos.items():
                try:
                    p = client_poly.get_last_trade(s).price if s.startswith("O:") else client_poly.get_snapshot_ticker("stocks", s).last_trade.p
                    mv += q * p * (100 if s.startswith("O:") else 1)
                except: pass

            log("💾 正在将数据写回数据库...")
            log_str = "[{}] {} | 🧠 {}".format(ts, " | ".join(reports) if reports else "🟡观望", cmd['thought'])
            
            supabase.table("drones").update({
                "balance": new_bal, "positions": new_pos, "total_assets": round(new_bal + mv, 2),
                "logs": ([log_str] + (d.get('logs') or []))[:20],
                "patrol_count": (int(d.get('patrol_count') or 0)) + 1,
                "memory": cmd['learning']
            }).eq("id", d["id"]).execute()
            
            log(f"✨ {d['name']} 巡检任务完成")
            
        except Exception as e:
            log(f"❌ {d['name']} 处理崩溃: {e}")

if __name__ == "__main__":
    patrol_and_evolve()
    log("🏁 巡检流程全部结束")