import os, json, pytz
import google.generativeai as genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

# --- 初始化 ---
client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel("gemini-3-flash-preview")

def get_market_data(tickers):
    """利用付费版 Snapshot 接口获取深度行情"""
    context = {}
    for t in tickers:
        try:
            # 获取股票快照
            snap = client_poly.get_snapshot_ticker("stocks", t)
            price = snap.last_trade.p if snap.last_trade else snap.prev_day.c
            
            # 获取期权链快照 (付费版支持更广的 limit)
            chain = client_poly.list_snapshot_options_chain(t, params={"limit": 15})
            options = []
            for o in chain:
                options.append({
                    "ticker": o.ticker,
                    "price": o.last_trade.p,
                    "strike": o.details.strike_price,
                    "type": o.details.contract_type,
                    "delta": getattr(o.greeks, 'delta', 'N/A')
                })
            context[t] = {"stock_price": price, "options": options}
        except Exception as e:
            print(f"扫描 {t} 失败: {e}")
    return context

def patrol_and_evolve():
    res = supabase.table("drones").select("*").execute()
    drones = res.data
    timestamp = datetime.now(pytz.timezone('US/Eastern')).strftime("%m-%d %H:%M")

    for d in drones:
        try:
            print(f"--- 🐝 工蜂巡检: {d['name']} ---")
            tickers = d.get('portfolio', ['AMD'])
            m_data = get_market_data(tickers)
            
            prompt = f"""你是 Hive 蜂巢工蜂 {d['name']}。性格: {d['persona']}。
            当前余额: ${d['balance']} | 当前持仓: {d.get('positions')}
            实时行情数据: {json.dumps(m_data)}
            
            请分析并决定：买入期权/股票、卖出、或构建组合。
            返回纯JSON: {{
                "trades": [{"action":"BUY/SELL", "symbol":"代码", "qty":数量, "price":价格}],
                "thought": "基于指标的分析",
                "learning": "巡检复盘"
            }}
            """
            
            res_ai = model.generate_content(prompt).text.strip()
            cmd = json.loads(res_ai.replace("```json", "").replace("```", "").strip())
            
            # --- 交易执行逻辑 ---
            new_balance = float(d.get('balance', 10000.0))
            new_positions = d.get('positions', {}) or {}
            trade_logs = []

            for t in cmd.get('trades', []):
                symbol = t['symbol']
                # 资产总值 = 现金 + 资产列表。买入瞬间资产基本守恒
                multiplier = 100 if "O:" in symbol else 1
                cost = float(t['qty']) * float(t['price']) * multiplier
                
                if t['action'] == 'BUY' and new_balance >= cost:
                    new_balance -= cost
                    new_positions[symbol] = new_positions.get(symbol, 0) + t['qty']
                    trade_logs.append(f"🟢买入 {symbol} x{t['qty']}")
                elif t['action'] == 'SELL' and new_positions.get(symbol, 0) >= t['qty']:
                    new_balance += cost
                    new_positions[symbol] -= t['qty']
                    if new_positions[symbol] <= 0: del new_positions[symbol]
                    trade_logs.append(f"🔴卖出 {symbol} x{t['qty']}")

            # --- 计算最新总资产 ---
            mkt_val = 0.0
            for s, q in new_positions.items():
                try:
                    # 优先从巡检到的 m_data 中取价，确保资产守恒
                    base_t = s.split(':')[1][:4] if "O:" in s else s
                    price = m_data.get(base_t, {}).get('stock_price', 0)
                    if "O:" in s:
                        # 如果是期权，寻找巡检数据中的对应价格
                        opts = m_data.get(base_t, {}).get('options', [])
                        price = next((o['price'] for o in opts if o['ticker'] == s), 0)
                    mkt_val += float(q) * float(price) * (100 if "O:" in s else 1)
                except: pass

            log_desc = " | ".join(trade_logs) if trade_logs else "🟡巡检不动"
            log_entry = f"[{timestamp}] {log_desc} | 🧠 {cmd['thought']}"
            
            # --- 同步回数据库 ---
            update_data = {
                "balance": new_balance,
                "positions": new_positions,
                "logs": ([log_entry] + (d.get('logs') or []))[:20],
                "patrol_count": (d.get('patrol_count', 0) or 0) + 1,
                "total_assets": new_balance + mkt_val,
                "memory": cmd['learning']
            }
            supabase.table("drones").update(update_data).eq("id", d["id"]).execute()
            print(f"✅ {d['name']} 巡检完成，总资产: ${update_data['total_assets']}")

        except Exception as e:
            print(f"❌ {d['name']} 失败: {e}")

if __name__ == "__main__":
    patrol_and_evolve()