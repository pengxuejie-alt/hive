import streamlit as st
import re, json, time, os, random, pytz
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai
from polygon import RESTClient

# --- 1. 初始化与工具函数 ---
VERSION = "v6.1 (Tiger-Eye Engine)"
st.set_page_config(page_title="Hive 智能金融", layout="wide")

def get_config(key): return os.environ.get(key) or st.secrets.get(key)

# 💡 参考附件：安全获取属性值函数
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

@st.cache_resource
def init_clients():
    try:
        return {
            "supabase": create_client(get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")),
            "gen_client": genai.Client(api_key=get_config("GEMINI_KEY")),
            "poly_client": RESTClient(api_key=get_config("POLYGON_KEY"))
        }
    except Exception as e: return None

cl = init_clients()
supabase, gen_client, poly_client = cl["supabase"], cl["gen_client"], cl["poly_client"]

# --- 2. 虎之眼级别：穿透式行情抓取 ---
def fetch_tiger_eye_data(ticker):
    try:
        ticker = ticker.upper()
        # 同时抓取 Snapshot 和昨日收盘 (Previous Close) 作为保底
        snap = poly_client.get_snapshot_ticker("stocks", ticker)
        prev = poly_client.get_previous_close_agg(ticker)
        y_close = get_val(prev[0] if prev else None, 'close')
        
        # 提取各个价格层级
        lt = getattr(snap, 'last_trade', None)
        lq = getattr(snap, 'last_quote', None)
        
        # 优先级逻辑：
        # 1. 最后成交价 (p)
        tp = get_val(lt, 'p', 'price') 
        # 2. 买卖价中值 (Bid/Ask mid)
        bp = get_val(lq, 'p', 'bid')
        ap = get_val(lq, 'P', 'ask')
        mid_p = (bp + ap) / 2 if (bp > 0 and ap > 0) else 0
        
        # 💡 最终穿透定价逻辑：成交价 > 买卖中值 > 昨日收盘价
        curr_p = tp if tp > 0 else (mid_p if mid_p > 0 else y_close)
        
        return {"代码": ticker, "现价": curr_p, "来源": "Trade" if tp > 0 else ("Quote" if mid_p > 0 else "PrevClose")}
    except Exception as e:
        return {"代码": ticker, "现价": 0, "error": str(e)}

# --- 3. 演化核心逻辑 ---
def execute_worker_cycle(d, slot):
    with slot:
        try:
            st.write("📡 **正在启动穿透式情报搜集...**")
            targets = d.get('portfolio', ['GLD'])
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(fetch_tiger_eye_data, targets))
            
            # 记录情报
            nectar_data = {r['代码']: {"现价": r['现价']} for r in results if r['现价'] > 0}
            st.table(results) # 💡 这里会清晰显示每一项的来源

            if not nectar_data:
                st.error("❌ 虎眼穿透失败：所有层级价格均不可得。请检查 API Key 权限。")
                return

            st.write("🧠 **正在进行跨标的研判...**")
            prompt = f"你是金融工蜂{d['name']}。性格:{d['persona']}。现金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data)}。请用中文写下思考过程并返回决策JSON。"
            r = gen_client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            if isinstance(decision, list): decision = decision[0]
            
            st.success(f"💭 思考: {decision.get('thought')}")

            # 交易结算
            nb, np, reports = float(d.get('balance', 100000)), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym = t.get('ticker', '').upper()
                px = nectar_data.get(sym, {}).get('现价', 0)
                if px <= 0: continue
                qty = t.get('qty', 0)
                cost = qty * px * (100 if len(sym) > 6 else 1)
                
                if t.get('action') == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"买入 {sym}@{px}")
                elif t.get('action') == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"卖出 {sym}@{px}")

            res_str = " | ".join(reports) if reports else "观望"
            mv = sum(q * nectar_data.get(s, {}).get('现价', 0) for s, q in np.items())
            
            # 💡 精准写入你数据库的 patrol_count 字段
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {res_str} | {decision.get('thought')}"] + (d.get('logs') or []))[:10],
                "patrol_count": (d.get('patrol_count', 0) + 1)
            }).eq("id", d["id"]).execute()
            
            st.write(f"📝 **结果: {res_str}**")
        except Exception as e: st.error(f"失败: {e}")

# --- 4. 界面逻辑 ---
# ... (首页、Tab 档案、孵化、管理逻辑保持 v6.0 架构) ...