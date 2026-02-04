import streamlit as st

# --- 🚨 坑 1 & 5: 必须在顶层声明，防止 NameError 和白屏 ---
VERSION = "v7.9 (Hardened Tiger-Eye)"
st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")
st.caption(f"{VERSION} | 严格遵循六大避坑红线 | 行情优先模式")

# --- 🚨 坑 3: 库引用对正 (使用 google-genai) ---
import json, time, os, random, pytz
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from supabase import create_client
from google import genai  # ✅ 修正
from polygon import RESTClient

# --- 🚨 坑 2: 虎眼核心工具函数 (1:1 还原数据读出能力) ---
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

@st.cache_resource
def init_hive_engine():
    try:
        pk, gk = st.secrets["POLYGON_KEY"], st.secrets["GEMINI_KEY"]
        su, sk = st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
        return {
            "supabase": create_client(su, sk),
            "gen_client": genai.Client(api_key=gk),
            "poly": RESTClient(api_key=pk)
        }, None
    except Exception as e:
        return None, str(e)

# --- 🚨 坑 6: 行情采集过程透明化 ---
def fetch_tiger_data(tk, poly):
    try:
        tz = pytz.timezone('US/Eastern')
        # A. 现货三级穿透 (虎眼逻辑)
        sn = poly.get_snapshot_ticker("stocks", tk.upper())
        prev = poly.get_previous_close_agg(tk.upper())
        y_close = get_val(prev[0] if prev else None, 'close')
        lt = getattr(sn, 'last_trade', None)
        
        # 严格取价：成交价 > 昨日收盘
        curr_p = get_val(lt, 'p', 'price') or y_close
        
        # B. 期权链分层穿透 (同步虎眼筛选逻辑)
        rows = []
        chain = poly.list_snapshot_options_chain(tk.upper(), params={
            "strike_price.gte": curr_p * 0.9,
            "strike_price.lte": curr_p * 1.1,
            "limit": 15
        })
        
        for o in chain:
            vol, oi = get_val(o.day, 'volume'), get_val(o, 'open_interest')
            # 价格
            olt, olq = getattr(o, 'last_trade', None), getattr(o, 'last_quote', None)
            op = get_val(olt, 'p') or (get_val(olq, 'p', 'bid') + get_val(olq, 'P', 'ask'))/2
            if op <= 0: continue
            
            rows.append({
                "信号": "🔥新开仓" if (vol > oi and vol > 100) else "-",
                "合约": o.details.ticker,
                "行权价": o.details.strike_price,
                "现价": round(op, 3),
                "成交量": int(vol),
                "IV": f"{get_val(o, 'implied_volatility')*100:.1f}%",
                "DTE": (datetime.strptime(o.details.expiration_date, '%Y-%m-%d').replace(tzinfo=tz) - datetime.now(tz)).days
            })
        
        df = pd.DataFrame(rows).sort_values(by="成交量", ascending=False) if rows else pd.DataFrame()
        return {"tk": tk, "price": curr_p, "df": df, "status": "OK"}
    except Exception as e:
        return {"tk": tk, "price": 0.0, "df": pd.DataFrame(), "status": f"Error: {e}"}

# --- 演化主逻辑 ---
def execute_worker(d, slot, clients):
    with slot:
        targets = d.get('portfolio') or ['GLD']
        st.write(f"📡 **正在同步虎眼数据流: {targets}**")
        
        # 1. 强制先读行情
        results = []
        with ThreadPoolExecutor(max_workers=5) as exe:
            futures = {exe.submit(fetch_tiger_data, tk, clients['poly']): tk for tk in targets}
            for f in as_completed(futures, timeout=15):
                results.append(f.result())
        
        # 2. 🚨 坑 6: 透明展示数据，绝不跳过表格
        valid_intel = {}
        for res in results:
            if res['status'] == "OK":
                st.subheader(f"💎 {res['tk']} 情报 (现价: ${res['price']})")
                if not res['df'].empty:
                    st.dataframe(res['df'], use_container_width=True)
                    valid_intel[res['tk']] = {"price": res['price'], "options": res['df'].head(5).to_dict('records')}
                else:
                    st.warning(f"{res['tk']} 未发现活跃期权链")
            else:
                st.error(f"{res['tk']} 采集失败: {res['status']}")

        if not valid_intel: return

        # 3. 研判
        st.write("🧠 **中枢研判中...**")
        prompt = f"你是工蜂{d['name']}。行情:{json.dumps(valid_intel)}。请中文分析并返回决策JSON。"
        try:
            r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            st.success(f"💭 决策: {decision.get('thought')}")
        except: st.error("AI 研判异常")

# --- 🚨 坑 4 & 5: 界面按钮与面板持久化 ---
clients, err = init_hive_engine()
if err: st.error(err); st.stop()

# 预取数据确保列表不消失
try:
    d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except:
    d_res = []

h1, h2 = st.columns([4, 1])
full_fly = h2.button("🚀 集群全量放飞", type="primary", use_container_width=True)

if full_fly and d_res:
    for d in d_res:
        with st.status(f"🐝 调度 {d['name']}...", expanded=True):
            execute_worker(d, st.container(), clients)
    st.success("✅ 全部任务结束"); st.button("刷新"); st.stop()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res: st.info("空。")
    for d in d_res:
        label = f"🐝 {d.get('name')} | ${d.get('total_assets',0):,.2f} | 巡逻: {d.get('patrol_count',0)}"
        with st.expander(label):
            st.write(f"🧬 **特质基因:** {d.get('style', '通用')}")
            st.write("**📦 持仓:**"); st.json(d.get('positions', {}))
            if st.button(f"🚀 单独放飞", key=f"f_{d['id']}"):
                execute_worker(d, st.container(), clients)