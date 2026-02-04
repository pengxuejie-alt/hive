import streamlit as st

# --- 1. 架构红线：全局常量锁死 (严禁 NameError) ---
VERSION = "v7.4 (Tiger-Eye Logic Sync)"
STRATEGY_LIB = {
    "波动率专家": "专注于 IV 偏离，识别回归或突破时机。",
    "末日博弈": "聚焦高 Gamma，捕捉极速爆发收益。",
    "机构大单": "监控 OI/Vol 异动，识别主力新开仓信号。"
}

# --- 2. UI 框架强制先行渲染 (严禁白屏) ---
st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

import re, json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 3. 核心工具函数 (同步虎之眼) ---
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

@st.cache_resource
def init_hive_engine():
    try:
        from supabase import create_client
        from google import genai
        from polygon import RESTClient
        return {
            "supabase": create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]),
            "gen_client": genai.Client(api_key=st.secrets["GEMINI_KEY"]),
            "poly": RESTClient(api_key=st.secrets["POLYGON_KEY"])
        }, None
    except Exception as e: return None, str(e)

# --- 4. 虎眼穿透引擎 (精简集成版) ---
def fetch_tiger_intel(ticker, poly):
    try:
        tk = ticker.upper()
        # 1. 现货三级穿透 (同步虎之眼)
        snap = poly.get_snapshot_ticker("stocks", tk)
        prev = poly.get_previous_close_agg(tk)
        y_close = get_val(prev[0] if prev else None, 'close')
        
        lt, lq = getattr(snap, 'last_trade', None), getattr(snap, 'last_quote', None)
        tp = get_val(lt, 'p', 'price') 
        mid_p = (get_val(lq, 'p', 'bid') + get_val(lq, 'P', 'ask')) / 2 if (get_val(lq, 'p', 'bid') > 0) else 0
        
        curr_p = tp if tp > 0 else (mid_p if mid_p > 0 else y_close)
        
        # 2. 期权链分层筛选 (仿虎眼：筛选行权价 ±10%)
        options_intel = []
        try:
            chain = poly.list_snapshot_options_chain(tk, params={
                "strike_price.gte": curr_p * 0.9,
                "strike_price.lte": curr_p * 1.1,
                "limit": 10
            })
            for o in chain:
                vol, oi = get_val(o.day, 'volume'), get_val(o, 'open_interest')
                # 标记新开仓信号
                sig = "🔥新开仓" if (vol > oi and vol > 100) else "-"
                options_intel.append({
                    "信号": sig,
                    "合约": o.details.ticker,
                    "类型": o.details.contract_type,
                    "行权价": o.details.strike_price,
                    "现价": get_val(o.day, 'c', 'close'),
                    "成交量": int(vol)
                })
        except: pass

        return {
            "代码": tk, 
            "现价": curr_p, 
            "来源": "Trade" if tp > 0 else ("Quote" if mid_p > 0 else "Prev"),
            "期权数据": options_intel
        }
    except:
        return {"代码": ticker, "现价": 0.0, "来源": "Timeout", "期权数据": []}

# --- 5. 演化核心执行 ---
def run_evolution(d, slot, clients):
    with slot:
        try:
            tks = d.get('portfolio') or ['GLD']
            st.write(f"📡 **正在同步虎眼穿透逻辑: {tks}**")
            
            # 并行抓取
            results = []
            with ThreadPoolExecutor(max_workers=5) as exe:
                futures = {exe.submit(fetch_tiger_intel, tk, clients["poly"]): tk for tk in tks}
                for f in as_completed(futures, timeout=8):
                    results.append(f.result())
            
            # 💡 精简展示：模仿虎眼的表格化
            for res in results:
                st.write(f"🟢 **{res['代码']}** (现价: ${res['现价']} | 来源: {res['来源']})")
                if res['期权数据']:
                    st.dataframe(res['期权数据'], use_container_width=True)
            
            valid_px = {r['代码']: r['现价'] for r in results if r['现价'] > 0}
            if not valid_px: st.warning("未能获取有效行情"); return

            # 敏捷研判
            style = d.get('style') or "波动率专家"
            prompt = f"你是{style}。行情:{json.dumps(results)}。现金:{d['balance']}。请分析并返回决策JSON。"
            r = clients["gen_client"].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            
            # 自动结算逻辑 (此处包含 patrol_count 累加)
            # ...
            st.success(f"💭 {d['name']} 研判完成: {decision.get('thought')}")
        except Exception as e: st.error(f"演化失败: {e}")

# --- 6. UI 主逻辑 (蜜蜂档案永远最先加载) ---
clients, err = init_hive_engine()
if err: st.error(err); st.stop()

# 数据预加载
try:
    d_res = clients["supabase"].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

h1, h2 = st.columns([4, 1])
with h1: st.caption(f"{VERSION} | 虎眼穿透逻辑已同步 | 蜜蜂档案保护中")
full_fly = h2.button("🚀 集群全量放飞", type="primary", use_container_width=True)

if full_fly and d_res:
    for d in d_res:
        with st.status(f"🐝 调度 {d['name']}...", expanded=True):
            run_evolution(d, st.container(), clients)
    st.success("✅ 放飞任务完成"); st.button("刷新"); st.stop()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])
with tabs[0]:
    if not d_res: st.info("蜂巢空。")
    for d in d_res:
        label = f"🐝 {d.get('name')} | {d.get('style','-')} | ${d.get('total_assets',0):,.2f} | 巡逻: {d.get('patrol_count',0)}次"
        with st.expander(label):
            col1, col2 = st.columns(2)
            with col1: st.write(f"🧬 **特质基因:** {d.get('style', '波动率专家')}")
            with col2: st.write("**📦 持仓:**"); st.json(d.get('positions', {}))
            if st.button(f"🚀 单独放飞", key=f"f_{d['id']}"):
                run_evolution(d, st.container(), clients)
            for l in (d.get('logs') or [])[:3]: st.caption(l)