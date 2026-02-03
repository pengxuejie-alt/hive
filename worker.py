import os, json, pytz, sys
from google import genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()

log("🚀 极速版脚本启动...")

try:
    # 增加连接超时配置
    client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
    supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
    gen_client = genai.Client(api_key=os.environ.get("GEMINI_KEY"))
    MODEL_ID = "gemini-2.0-flash-exp"
    log("✅ 客户端初始化完成")
except Exception as e:
    log(f"❌ 初始化失败: {e}")
    sys.exit(1)

def get_market_data_fast(tickers):
    """优化版行情获取：仅抓取活跃的、近期的期权合约"""
    context = {}
    for t in tickers:
        try:
            log(f"🔍 正在穿透标的价格: {t}")
            lt = client_poly.get_last_trade(t)
            price = lt.price if lt and lt.price > 0 else 0
            
            # 💡 修复核心：不再请求全量 Snapshot，改用带参数的 list_snapshot_options_chain
            # 仅限制获取前 15 条，并增加过期时间过滤（可选）
            log(f"🔍 正在筛选活跃期权 (Limit 15): {t}")
            
            # 使用更轻量的调用方式，避免获取整个巨大的 GLD 链
            options_pool = []
            # 这里的 params 能够显著减少 Polygon 返回的数据量
            chain = client_poly.list_snapshot_options_chain(
                t, 
                params={"limit": 15, "sort": "volume", "order": "desc"}
            )
            
            for o in chain:
                # 只要最后成交价大于 0 且有成交量的活跃合约
                if getattr(o.day, 'v', 0) > 0 and o.last_trade.p > 0:
                    options_pool.append({
                        "ticker": o.ticker,
                        "price": o.last_trade.p,
                        "strike": o.details.strike_price,
                        "type": o.details.contract_type
                    })
            
            context[t] = {"price": price, "options": options_pool}
            log(f"📊 {t} 数据采集完毕 (合约数: {len(options_pool)})")
        except Exception as e:
            log(f"⚠️ {t} 采集失败: {str(e)[:50]}...")
            context[t] = {"price": 0, "options": []}
    return context

def patrol_and_evolve():
    log("📡 读取工蜂任务...")
    d_res = supabase.table("drones").select("*").execute()
    drones = d_res.data
    ts = datetime.now(pytz.timezone('US/Eastern')).strftime("%H:%M:%S")

    for d in drones:
        try:
            log(f"--- 🐝 巡检: {d['name']} ---")
            m_data = get_market_data_fast(d.get('portfolio', ['GLD']))
            
            log(f"🧠 调用演化脑 (Gemini)...")
            prompt = "工蜂{}。余额:{}。行情:{}。决策JSON: {{'trades':[], 'thought':'', 'learning':''}}".format(
                d['name'], d['balance'], json.dumps(m_data)
            )
            
            res = gen_client.models.generate_content(
                model=MODEL_ID, contents=prompt,
                config={'response_mime_type': 'application/json'}
            )
            cmd = json.loads(res.text)

            # 交易执行逻辑
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

            # 市值重估 (极速版：仅评估持有的那几个，不扫全链)
            log("💰 重估持仓价值...")
            mv = 0.0
            for s, q in new_pos.items():
                try:
                    p = client_poly.get_last_trade(s).price if s.startswith("O:") else client_poly.get_snapshot_ticker("stocks", s).last_trade.p
                    mv += q * p * (100 if s.startswith("O:") else 1)
                except: pass

            log("💾 同步数据库...")
            log_str = "[{}] {} | 🧠 {}".format(ts, " | ".join(reports) if reports else "🟡观望", cmd['thought'])
            
            supabase.table("drones").update({
                "balance": new_bal, "positions": new_pos, "total_assets": round(new_bal + mv, 2),
                "logs": ([log_str] + (d.get('logs') or []))[:20],
                "patrol_count": (int(d.get('patrol_count') or 0)) + 1,
                "memory": cmd['learning']
            }).eq("id", d["id"]).execute()
            
            log(f"✅ {d['name']} 演化成功")
        except Exception as e:
            log(f"❌ {d['name']} 异常: {e}")

if __name__ == "__main__":
    patrol_and_evolve()
    log("🏁 巡检全流程结束")