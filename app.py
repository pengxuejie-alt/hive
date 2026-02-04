import streamlit as st
import json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai
from polygon import RESTClient

# --- 1. 配置 ---
VERSION = "v5.9.1 (Field Alignment)"
st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

def get_config(key): return os.environ.get(key) or st.secrets.get(key)

@st.cache_resource
def init_clients():
    try:
        return {
            "supabase": create_client(get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")),
            "gen_client": genai.Client(api_key=get_config("GEMINI_KEY")),
            "poly_client": RESTClient(api_key=get_config("POLYGON_KEY"))
        }
    except: return None

cl = init_clients()
supabase, gen_client, poly_client = cl["supabase"], cl["gen_client"], cl["poly_client"]

# --- 2. 演化核心 (参数对齐版) ---
def fetch_detailed_nectar(ticker):
    try:
        ticker = ticker.upper()
        # 💡 调用 Snapshot 接口
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        
        # 调试信息：获取对象所有可用属性
        available_attrs = dir(sn)
        
        # 💡 Polygon 字段对齐逻辑 (重点修正)
        # 1. day 对象中的当前价格 (c: close)
        day_price = getattr(sn.day, 'c', 0) if hasattr(sn, 'day') and sn.day else 0
        # 2. last_trade 对象中的价格 (p: price)
        last_trade_price = getattr(sn.last_trade, 'p', 0) if hasattr(sn, 'last_trade') and sn.last_trade else 0
        # 3. prev_day 对象中的价格 (c: close)
        prev_price = getattr(sn.prev_day, 'c', 0) if hasattr(sn, 'prev_day') and sn.prev_day else 0
        
        final_px = day_price or last_trade_price or prev_price
        
        return {
            "代码": ticker,
            "当日现价(day.c)": day_price,
            "最后成交(last_trade.p)": last_trade_price,
            "昨日价格(prev_day.c)": prev_price,
            "最终选定": final_px,
            "原始属性清单": [a for a in available_attrs if not a.startswith('_')]
        }
    except Exception as e:
        return {"代码": ticker, "错误": str(e), "最终选定": 0}

def execute_worker_cycle(d, slot):
    with slot:
        try:
            st.write("📡 **第一步：行情穿透检索 (API 参数自检)...**")
            targets = d.get('portfolio', ['GLD'])
            
            with ThreadPoolExecutor(max_workers=5) as exe:
                raw_results = list(exe.map(fetch_detailed_nectar, targets))
            
            # 💡 强制显示 API 每一层级读取到的数据
            st.write("📥 **行情对齐详情:**")
            st.table(raw_results)
            
            nectar_data = {r['代码']: {"现价": r['最终选定']} for r in raw_results if r['最终选定'] > 0}
            
            if not nectar_data:
                st.error("❌ 严重错误：未读取到有效行情。请核对上表中的字段是否有值。")
                return

            # --- 第二步：研判 ---
            st.write("🧠 **第二步：中枢研判分析...**")
            prompt = f"你是金融工蜂{d['name']}。行情:{json.dumps(nectar_data)}。请用中文返回决策JSON:{{'thought':'分析','trades':[]}}"
            r = gen_client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            if isinstance(decision, list): decision = decision[0]
            st.success(f"💭 思考逻辑：{decision.get('thought')}")

            # --- 第三步：执行 ---
            st.write("⚖️ **第三步：执行指令结算...**")
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

            act_sum = " | ".join(reports) if reports else "观望"
            mv = sum(q * nectar_data.get(s, {}).get('现价', 0) for s, q in np.items())
            
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] 动作:{act_sum} | 思考:{decision.get('thought')}"] + (d.get('logs') or []))[:10],
                "patrol_count": (d.get('patrol_count', 0) + 1)
            }).eq("id", d["id"]).execute()
            
            st.write(f"📝 **演化结果：{act_sum}**")
        except Exception as e: st.error(f"❌ 流程崩溃: {e}")

# --- UI (全量放飞逻辑) ---
h1, h2 = st.columns([4, 1])
with h1: st.caption(f"{VERSION} | 正在穿透：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
full_fly = h2.button("🔥 一键全量放飞", type="primary", use_container_width=True)

d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data

if full_fly and d_res:
    for d in d_res:
        with st.status(f"🐝 正在放飞 {d['name']}...", expanded=True) as status:
            execute_worker_cycle(d, status)
    st.success("✅ 全部放飞完成")
    st.button("🔄 手动刷新")
    st.stop()