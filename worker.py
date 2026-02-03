import os, json, pytz, sys, time
from google import genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone, timedelta

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()

log("🚀 深度行情排查引擎启动...")

try:
    # 增加长连接配置
    client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
    supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
    gen_client = genai.Client(api_key=os.environ.get("GEMINI_KEY"))
    MODEL_ID = "gemini-3-flash-preview"
    log("✅ API 链路初始化完成")
except Exception as e:
    log(f"❌ 初始化失败: {e}")
    sys.exit(1)

def get_market_data_debug(tickers):
    """深度排查逻辑：确保期权链和股价必须拿到"""
    context = {}
    for t in tickers:
        try:
            log(f"--- 📡 正在拉取标的详情: {t} ---")
            # 1. 获取股价：改用 Snapshot 模式，它包含盘前盘后和上一个交易日的终值
            ticker_snapshot = client_poly.get_snapshot_ticker("stocks", t)
            price = 0
            if ticker_snapshot and ticker_snapshot.last_trade:
                price = ticker_snapshot.last_trade.p
            if price == 0 and ticker_snapshot.prev_day:
                price = ticker_snapshot.prev_day.c # 拿昨收价保底
            
            log(f"🎯 {t} 实时/昨收价: {price}")

            # 2. 获取期权链：必须想办法突破全量限制
            log(f"⛓️ 正在扫描 {t} 的期权快照链...")
            options_pool = []
            
            # 使用更严谨的分页或筛选，这里我们拿活跃度最高的前 20 个
            # 如果这里报错，说明是 API Key 权限或 Polygon 瞬时封禁
            try:
                # 显式增加 limit 参数并打印原始状态
                chain_gen = client_poly.list_snapshot_options_chain(
                    t, 
                    params={"limit": 20, "sort": "volume", "order": "desc"}
                )
                
                for o in chain_gen:
                    # 只要是有基本成交数据的合约都抓进来
                    opt_price = getattr(o.last_trade, 'p', 0)
                    if opt_price == 0 and o.day:
                        opt_price = getattr(o.day, 'c', 0)
                    
                    options_pool.append({
                        "ticker": o.ticker,
                        "strike": o.details.strike_price,
                        "type": o.details.contract_type,
                        "price": opt_price,
                        "vol": getattr(o.day, 'v', 0)
                    })
                log(f"✅ 成功抓取到 {len(options_pool)} 个活跃期权合约")
            except Exception as chain_err:
                log(f"❌ 期权链抓取失败核心原因: {str(chain_err)}")

            context[t] = {"price": price, "options": options_pool}
            
        except Exception as e:
            log(f"💥 {t} 总体采集崩溃: {e}")
    return context

def patrol_and_evolve():
    d_res = supabase.table("drones").select("*").execute()
    drones = d_res.data
    ts = datetime.now(pytz.timezone('US/Eastern')).strftime("%H:%M:%S")

    for d in drones:
        try:
            log(f"--- 🐝 正在处理工蜂: {d['name']} ---")
            m_data = get_market_data_debug(d.get('portfolio', ['GLD']))
            
            # 检查关键数据
            gld_data = m_data.get('GLD', {})
            if gld_data.get('price', 0) == 0:
                log(f"⚠️ 警告: {d['name']} 拿到的 GLD 价格依然为 0，请检查 Polygon Key 权限！")

            prompt = f"你是工蜂{d['name']}。性格:{d['persona']}。余额:{d['balance']}。行情:{json.dumps(m_data)}。决策JSON: {{'trades':[], 'thought':'', 'learning':''}}"
            
            res = gen_client.models.generate_content(
                model=MODEL_ID, contents=prompt,
                config={'response_mime_type': 'application/json'}
            )
            
            cmd = json.loads(res.text)
            if isinstance(cmd, list): cmd = cmd[0]
            
            # 交易执行逻辑 (此处保持不变)
            new_bal, new_pos, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            trades = cmd.get('trades', []) if isinstance(cmd, dict) else []
            for t in trades:
                sym, mult = t['symbol'], (100 if t['symbol'].startswith("O:") else 1)
                cost = float(t['qty']) * float(t['price']) * mult
                if t['action'] == 'BUY' and new_bal >= cost:
                    new_bal -= cost
                    new_pos[sym] = new_pos.get(sym, 0) + t['qty']
                    reports.append(f"🟢买入 {sym}")
                elif t['action'] == 'SELL' and new_pos.get(sym, 0) >= t['qty']:
                    new_bal += cost
                    new_pos[sym] -= t['qty']
                    if new_pos[sym] <= 0: del new_pos[sym]
                    reports.append(f"🔴卖出 {sym}")

            # 资产重估
            mv = 0.0
            for s, q in new_pos.items():
                try:
                    mv += q * client_poly.get_last_trade(s).price * (100 if s.startswith("O:") else 1)
                except: pass

            log("💾 正在回写数据库...")
            log_str = "[{}] {} | 🧠 {}".format(ts, " | ".join(reports) if reports else "🟡观望", cmd.get('thought', '...'))
            supabase.table("drones").update({
                "balance": new_bal, "positions": new_pos, "total_assets": round(new_bal + mv, 2),
                "logs": ([log_str] + (d.get('logs') or []))[:20],
                "patrol_count": (int(d.get('patrol_count') or 0)) + 1,
                "memory": cmd.get('learning', '')
            }).eq("id", d["id"]).execute()
            
            log(f"✨ {d['name']} 任务完成")
            time.sleep(2) # 蜂群间隔，保护 API

        except Exception as e:
            log(f"❌ {d['name']} 异常详情: {e}")

if __name__ == "__main__":
    patrol_and_evolve()