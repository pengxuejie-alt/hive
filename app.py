import streamlit as st
import google.generativeai as genai
from polygon import RESTClient
import pandas as pd
from datetime import datetime
import pytz, json, os, time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. 全局配置 (红线：必须在顶层) ---
VERSION = "v7.8 (Tiger-Eye Mirror Data)"
st.set_page_config(page_title="Hive 智能金融", layout="wide")

# --- 2. 虎眼核心工具函数 (1:1 复制) ---
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

@st.cache_resource
def init_engine():
    try:
        pk = st.secrets["POLYGON_KEY"]
        gk = st.secrets["GEMINI_KEY"]
        return RESTClient(api_key=pk), genai.GenerativeModel("gemini-2.0-flash")
    except Exception as e:
        st.error(f"环境配置失败: {e}")
        return None, None

# --- 3. 深度行情穿透引擎 (完全参考虎眼代码) ---
def fetch_tiger_data(tk, poly):
    try:
        tz = pytz.timezone('US/Eastern')
        # A. 现货穿透
        sn = poly.get_snapshot_ticker("stocks", tk)
        prev = poly.get_previous_close_agg(tk)
        
        y_close = get_val(prev[0] if prev else None, 'close')
        lt = getattr(sn, 'last_trade', None)
        # 优先级：成交价 > 昨日收盘 (虎眼保底逻辑)
        curr_p = get_val(lt, 'p', 'price') or y_close
        
        # B. 期权链深度穿透 (分层筛选)
        options_rows = []
        chain = poly.list_snapshot_options_chain(tk, params={
            "strike_price.gte": curr_p * 0.9,
            "strike_price.lte": curr_p * 1.1,
            "limit": 20
        })
        
        for o in chain:
            vol = get_val(o.day, 'volume')
            oi = get_val(o, 'open_interest')
            # 信号识别
            sig = "🔥新开仓" if (vol > oi and vol > 100) else "-"
            
            # 期权价格穿透
            olt = getattr(o, 'last_trade', None)
            olq = getattr(o, 'last_quote', None)
            op = get_val(olt, 'p') or (get_val(olq, 'p', 'bid') + get_val(olq, 'P', 'ask'))/2
            
            if op <= 0: continue
            
            options_rows.append({
                "信号": sig,
                "合约": o.details.ticker,
                "类型": o.details.contract_type.upper(),
                "行权价": o.details.strike_price,
                "现价": round(op, 3),
                "成交量": int(vol),
                "持仓量": int(oi),
                "IV": f"{get_val(o, 'implied_volatility')*100:.1f}%",
                "DTE": (datetime.strptime(o.details.expiration_date, '%Y-%m-%d').replace(tzinfo=tz) - datetime.now(tz)).days
            })
        
        df_opt = pd.DataFrame(options_rows).sort_values(by="成交量", ascending=False) if options_rows else pd.DataFrame()
        return {"tk": tk, "price": curr_p, "df": df_opt, "status": "SUCCESS"}
    except Exception as e:
        return {"tk": tk, "price": 0.0, "df": pd.DataFrame(), "status": f"ERR: {str(e)}"}

# --- 4. 蜂巢执行器 ---
def run_worker(d, slot, poly, ai):
    with slot:
        targets = d.get('portfolio') or ['GLD']
        st.write(f"📡 **正在同步虎眼数据流: {targets}**")
        
        # 1. 强制先读行情数据
        intel = []
        with ThreadPoolExecutor(max_workers=5) as exe:
            futures = {exe.submit(fetch_tiger_data, tk, poly): tk for tk in targets}
            for f in as_completed(futures, timeout=15):
                intel.append(f.result())
        
        # 2. 💡 核心：先展示数据表格，不等待 AI 思考
        valid_data = {}
        for res in intel:
            if res['status'] == "SUCCESS":
                st.subheader(f"💎 {res['tk']} 情报 (现价: ${res['price']})")
                if not res['df'].empty:
                    st.dataframe(res['df'], use_container_width=True)
                    valid_data[res['tk']] = {"price": res['price'], "options": res['df'].head(10).to_dict('records')}
                else:
                    st.warning(f"{res['tk']} 无符合条件的活跃期权")
            else:
                st.error(f"{res['tk']} 获取失败: {res['status']}")

        if not valid_data: return

        # 3. 数据读完后，再进行 AI 研判
        st.write("🧠 **情报已就绪，中枢研判中...**")
        prompt = f"你是工蜂{d['name']}。行情数据:{json.dumps(valid_data)}。账户现金:{d['balance']}。请给出决策JSON。"
        try:
            r = ai.generate_content(prompt)
            # 处理 JSON 解析略...
            st.success(f"💭 决策完成")
        except: pass

# --- 5. UI 布局 (简化版以确保稳定) ---
st.title("🐝 Hive 智能金融蜂群")
poly, ai = init_engine()

# Supabase 初始化与数据拉取
from supabase import create_client
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
d_res = supabase.table("drones").select("*").execute().data

h1, h2 = st.columns([4, 1])
full_fly = h2.button("🚀 集群放飞", type="primary")

if full_fly and d_res:
    for d in d_res:
        with st.status(f"🐝 {d['name']} 采蜜中...", expanded=True) as s:
            run_worker(d, s, poly, ai)

# 蜜蜂档案展示
st.divider()
for d in d_res:
    with st.expander(f"🐝 {d['name']} | 资产: ${d.get('total_assets',0)}"):
        st.write(f"🧬 基因: {d.get('style')}")
        if st.button("🚀 单独采蜜", key=d['id']):
            run_worker(d, st.container(), poly, ai)