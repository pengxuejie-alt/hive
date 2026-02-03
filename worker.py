import os, json, pytz
import google.generativeai as genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime, timezone

# --- 初始化 ---
# 强制检查环境变量，如果缺失会在 GitHub Actions 日志里直接报错
POLYGON_KEY = os.environ.get("POLYGON_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

if not all([POLYGON_KEY, SUPABASE_URL, SUPABASE_KEY, GEMINI_KEY]):
    print("❌ 错误: 环境变量配置不全，请检查 GitHub Secrets")
    exit(1)

client_poly = RESTClient(api_key=POLYGON_KEY)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-3-flash-preview")

def get_market_data(tickers):
    context = {}
    for t in tickers:
        try:
            # 付费版高级接口
            snap = client_poly.get_snapshot_ticker("stocks", t)
            price = snap.last_trade.p if snap.last_trade and snap.last_trade.p > 0 else snap.prev_day.c
            chain = client_poly.list_snapshot_options_chain(t, params={"limit": 10})
            options = [{"ticker": o.ticker, "price": o.last_trade.p, "type": o.details.contract_type} for o in chain]
            context[t] = {"stock_price": price, "options": options}
        except Exception as e:
            print(f"⚠️ 扫描 {t} 异常: {e}")
    return context

def patrol_and_evolve():
    print("🚀 开始全员巡检...")
    res = supabase.table("drones").select("*").execute()
    drones = res.data
    
    # 获取美东时间
    et_tz = pytz.timezone('US/Eastern')
    ts = datetime.now(et_tz).strftime("%m-%d %H:%M")

    for d in drones:
        try:
            print(f"--- 🐝 正在处理工蜂: {d['name']} (ID: {d['id']}) ---")
            m_data = get_market_data(d.get('portfolio', ['AMD']))
            
            prompt = f"""你是 Hive 蜂巢工蜂 {d['name']}。性格: {d['persona']}。
            当前余额: ${d['balance']} | 持仓: {d.get('positions')}
            实时行情: {json.dumps(m_data)}
            请分析并决策。返回纯JSON: {{'trades':[], 'thought':'', 'learning':''}}
            """
            
            res_ai = model.generate_content(prompt).text.strip()
            cmd = json.loads(res_ai.replace("```json", "").replace("```", "").strip())
            
            # 资产处理逻辑
            new_bal = float(d['balance'])
            new_pos = (d.get('positions', {}) or {}).copy()
            trade_summaries = []

            for t in cmd.get('trades', []):
                symbol, qty, price = t['symbol'], t['qty'], t['price']
                mult = 100 if "O:" in symbol else 1
                cost = qty * price * mult
                
                if t['action'] == 'BUY' and new_bal >= cost:
                    new_bal -= cost
                    new_pos[symbol] = new_pos.get(symbol, 0) + qty
                    trade_summaries.append(f"🟢买入 {symbol}")
                elif t['action'] == 'SELL' and new_pos.get(symbol, 0) >= qty:
                    new_bal += cost
                    new_pos[symbol] -= qty
                    if new_pos[symbol] <= 0: del new_pos[symbol]
                    trade_summaries.append(f"🔴卖出 {symbol}")

            # 资产估值
            mkt_val = 0.0
            for s, q in new_pos.items():
                try:
                    p = client_poly.get_last_trade(s).price if "O:" in s else client_poly.get_snapshot_ticker("stocks", s).last_trade.p
                    mkt_val += q * p * (100 if "O:" in s else 1)
                except: pass

            # 强制日志字符串化，防止 JSON 解析错误
            action_text = " | ".join(trade_summaries) if trade_summaries else "🟡巡检不动"
            new_log_str = f"[{ts}] {action_text} | 🧠 {cmd['thought']}"
            
            # 准备写回数据库
            update_payload = {
                "balance": new_bal,
                "positions": new_pos,
                "total_assets": new_bal + mkt_val,
                "logs": ([new_log_str] + (d.get('logs') or []))[:20],
                "patrol_count": (int(d.get('patrol_count') or 0)) + 1, # 计数器递增
                "memory": cmd['learning']
            }
            
            # 执行更新
            save_res = supabase.table("drones").update(update_payload).eq("id", d["id"]).execute()
            if save_res.data:
                print(f"✅ {d['name']} 更新成功，巡检次数: {update_payload['patrol_count']}")
            else:
                print(f"❌ {d['name']} 更新失败，请检查数据库")

        except Exception as e:
            print(f"💥 {d['name']} 巡检崩溃: {e}")

if __name__ == "__main__":
    patrol_and_evolve()