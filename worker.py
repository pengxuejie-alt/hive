import os
import json
import pytz
import google.generativeai as genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

# --- 1. 环境初始化 ---
# 从环境变量读取 Key (GitHub Actions 环境下自动注入)
POLYGON_KEY = os.environ.get("POLYGON_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

# 检查必要配置
if not all([POLYGON_KEY, SUPABASE_URL, SUPABASE_KEY, GEMINI_KEY]):
    print("❌ 错误: 环境变量配置不完整，请检查 GitHub Secrets。")
    exit(1)

# 初始化客户端
client_poly = RESTClient(api_key=POLYGON_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-3-flash-preview")

def get_market_data(tickers):
    """
    针对付费版接口优化的深度行情扫描
    """
    context = {}
    for t in tickers:
        try:
            # 1. 股票/ETF 实时价格穿透
            lt = client_poly.get_last_trade(t)
            # 如果是盘中，获取最新成交价；否则获取快照中的昨日收盘价作为参考
            price = lt.price if lt and lt.price > 0 else 0
            if price == 0:
                snap = client_poly.get_snapshot_ticker("stocks", t)
                price = snap.prev_day.c if snap and snap.prev_day else 0

            # 2. 期权链扫描 (仅筛选今日有成交量的活跃合约)
            chain = client_poly.list_snapshot_options_chain(t, params={"limit": 25})
            options_pool = []
            for o in chain:
                # 过滤今日成交量(v) > 0 的合约，确保 AI 交易的是真实存在的流动性
                vol = getattr(o.day, 'v', 0)
                if vol > 0:
                    options_pool.append({
                        "ticker": o.ticker,
                        "price": o.last_trade.p,
                        "strike": o.details.strike_price,
                        "type": o.details.contract_type,
                        "vol": vol,
                        "iv": getattr(o, 'implied_volatility', 'N/A'),
                        "delta": getattr(o.greeks, 'delta', 'N/A') if hasattr(o, 'greeks') else 'N/A'
                    })
            
            context[t] = {
                "current_price": price,
                "active_options": options_pool[:15]  # 给 AI 精选 15 个活跃合约
            }
        except Exception as e:
            print(f"⚠️ 标的 {t} 行情扫描跳过: {e}")
    return context

def patrol_and_evolve():
    # 1. 获取数据库中所有存活的工蜂
    print("🚀 Hive 蜂巢开始放飞巡检...")
    res = supabase.table("drones").select("*").execute()
    drones = res.data
    
    if not drones:
        print("📭 蜂巢为空，无需巡检。")
        return

    # 设置时区
    et_tz = pytz.timezone('US/Eastern')
    ts_str = datetime.now(et_tz).strftime("%m-%d %H:%M:%S")

    for d in drones:
        try:
            print(f"--- 🐝 正在巡检工蜂: {d['name']} (ID: {d['id']}) ---")
            
            # 2. 行情扫描
            portfolio = d.get('portfolio', ['GLD'])
            m_data = get_market_data(portfolio)
            
            # 3. AI 决策逻辑
            prompt = f"""
            你是 Hive 蜂巢的工蜂 {d['name']}。
            你的性格基因: {d['persona']}
            当前账户余额: ${d['balance']}
            当前持仓列表: {d.get('positions')}
            
            【实时行情数据(盘中)】:
            {json.dumps(m_data)}
            
            任务: 基于性格和行情决定操作。你可以买入/卖出多项资产构建组合，或保持不动(HOLD)。
            要求: 必须使用行情中给出的价格(price)进行撮合。
            
            请返回纯 JSON 格式（不要 Markdown 包装）:
            {{
                "trades": [{"action":"BUY/SELL", "symbol":"代码", "qty":数量, "price":价格}],
                "thought": "基于盘中数据的决策分析",
                "learning": "本次巡检的进化心得"
            }}
            """
            
            response = model.generate_content(prompt).text.strip()
            # 简单清洗 JSON
            clean_json = response.replace("```json", "").replace("```", "").strip()
            cmd = json.loads(clean_json)
            
            # 4. 交易撮合与资产计算
            new_balance = float(d.get('balance', 10000.0))
            new_positions = (d.get('positions', {}) or {}).copy()
            trade_reports = []

            for t in cmd.get('trades', []):
                sym = t['symbol']
                qty = t['qty']
                px = t['price']
                
                # 期权杠杆乘数 100
                multiplier = 100 if sym.startswith("O:") else 1
                total_cost = qty * px * multiplier
                
                if t['action'] == 'BUY' and new_balance >= total_cost:
                    new_balance -= total_cost
                    new_positions[sym] = new_positions.get(sym, 0) + qty
                    trade_reports.append(f"🟢买入 {sym} @{px}")
                elif t['action'] == 'SELL' and new_positions.get(sym, 0) >= qty:
                    new_balance += total_cost
                    new_positions[sym] -= qty
                    if new_positions[sym] <= 0:
                        del new_positions[sym]
                    trade_reports.append(f"🔴卖出 {sym} @{px}")

            # 5. 实时重算总资产 (Total Assets)
            # 使用最后成交价对现有持仓进行现值评估
            current_mkt_val = 0.0
            for s, q in new_positions.items():
                try:
                    # 优先调用付费版接口获取实时估值
                    p = client_poly.get_last_trade(s).price if s.startswith("O:") else client_poly.get_snapshot_ticker("stocks", s).last_trade.p
                    current_mkt_val += q * p * (100 if s.startswith("O:") else 1)
                except:
                    # 如果获取失败，使用成交时的价格作为保底
                    current_mkt_val += 0.0 

            # 6. 数据固化与写回
            action_desc = " | ".join(trade_reports) if trade_reports else "🟡盘中观察/保持不动"
            log_entry = f"[{ts_str}] {action_desc} | 🧠 {cmd['thought']}"
            
            update_payload = {
                "balance": new_balance,
                "positions": new_positions,
                "total_assets": new_balance + current_mkt_val,
                "logs": ([log_entry] + (d.get('logs') or []))[:20],  # 滚动保留20条日志
                "patrol_count": (int(d.get('patrol_count') or 0)) + 1,  # 强制递增
                "memory": cmd['learning']
            }
            
            supabase.table("drones").update(update_payload).eq("id", d["id"]).execute()
            print(f"✅ {d['name']} 同步完成。总资产: ${update_payload['total_assets']:.2f}, 计数: {update_payload['patrol_count']}")

        except Exception as e:
            print(f"❌ 工蜂 {d.get('name')} 巡检中途崩溃: {e}")
            continue

if __name__ == "__main__":
    patrol_and_evolve()