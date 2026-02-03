import os, json, pytz
import google.generativeai as genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

# --- 初始化 (付费版 API) ---
client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel("gemini-3-flash-preview")

def patrol_and_evolve():
    # 获取所有工蜂
    res = supabase.table("drones").select("*").execute()
    drones = res.data
    
    et_tz = pytz.timezone('US/Eastern')
    ts = datetime.now(et_tz).strftime("%m-%d %H:%M")

    print(f"🚀 开始执行 Hive 巡检循环，共计 {len(drones)} 只工蜂...")

    for d in drones:
        try:
            print(f"--- 🐝 正在处理: {d['name']} ---")
            
            # 1. 获取市场快照 (利用付费接口)
            portfolio = d.get('portfolio', ['GLD'])
            m_data = {}
            for ticker in portfolio:
                try:
                    # 尝试从 ticker 中提取股票代码 (处理 O: 前缀)
                    base_symbol = ticker.split(':')[1][:3] if "O:" in ticker else ticker
                    snap = client_poly.get_snapshot_ticker("stocks", base_symbol)
                    m_data[ticker] = {
                        "price": snap.last_trade.p if snap.last_trade else snap.prev_day.c,
                        "day_change": snap.todays_change_percent
                    }
                except: m_data[ticker] = "Data access error"

            # 2. AI 决策过程
            prompt = f"你是 Hive 工蜂 {d['name']}。性格: {d['persona']}。余额: {d['balance']}。行情: {m_data}。请决策并返回纯JSON: {{'trades':[], 'thought':'', 'learning':''}}"
            ai_res = model.generate_content(prompt).text.strip()
            cmd = json.loads(ai_res.replace("```json", "").replace("```", "").strip())

            # 3. 计算资产变动 (组合交易支持)
            new_bal = float(d.get('balance', 10000.0))
            new_pos = (d.get('positions', {}) or {}).copy()
            logs = []

            for t in cmd.get('trades', []):
                sym, qty, px = t['symbol'], t['qty'], t['price']
                mult = 100 if "O:" in sym else 1
                cost = qty * px * mult
                if t['action'] == 'BUY' and new_bal >= cost:
                    new_bal -= cost
                    new_pos[sym] = new_pos.get(sym, 0) + qty
                    logs.append(f"🟢买入 {sym}")
                elif t['action'] == 'SELL' and new_pos.get(sym, 0) >= qty:
                    new_bal += cost
                    new_pos[sym] -= qty
                    if new_pos[sym] <= 0: del new_pos[sym]
                    trade_logs.append(f"🔴卖出 {sym}")

            # 4. 实时算账：同步 total_assets 字段
            mkt_val = 0.0
            for s, q in new_pos.items():
                try:
                    p = client_poly.get_last_trade(s).price if "O:" in s else client_poly.get_snapshot_ticker("stocks", s).last_trade.p
                    mkt_val += q * p * (100 if "O:" in s else 1)
                except: pass

            # 5. 强制执行更新 (即使没有任何交易)
            update_payload = {
                "balance": new_bal,
                "positions": new_pos,
                "total_assets": new_bal + mkt_val,
                "logs": ([f"[{ts}] {' | '.join(logs) or '🟡保持不动'} | 🧠 {cmd['thought']}"] + (d.get('logs') or []))[:20],
                "patrol_count": (d.get('patrol_count') or 0) + 1, # 确保计数器加1
                "memory": cmd['learning']
            }

            # 关键：独立更新每一只工蜂，确保互不干扰
            supabase.table("drones").update(update_payload).eq("id", d["id"]).execute()
            print(f"✅ {d['name']} 巡检数据已同步，计数器: {update_payload['patrol_count']}")

        except Exception as e:
            print(f"❌ {d['name']} 巡检失败，原因: {e}")
            continue # 跳过故障蜂，继续处理下一只

if __name__ == "__main__":
    patrol_and_evolve()