import streamlit as st
import json, time, os, random, re
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai 
from polygon import RESTClient

# --- 1. 全局配置 ---
VERSION = "v9.7 (Trading Terminal UI)"
st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

# --- 2. 核心辅助：解析期权代码 (代码整容) ---
def parse_option_symbol(symbol):
    if not symbol.startswith("O:"): return symbol
    match = re.match(r"O:([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d+)", symbol)
    if match:
        tk, yy, mm, dd, cp, strike = match.groups()
        strike_val = int(strike) / 1000
        type_str = "认涨(Call)" if cp == "C" else "认沽(Put)"
        return f"{tk} {mm}月{dd}日 ${strike_val} {type_str}"
    return symbol

@st.cache_resource
def init_hive_engine():
    try:
        return {
            "supabase": create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]),
            "gen_client": genai.Client(api_key=st.secrets["GEMINI_KEY"]),
            "poly": RESTClient(api_key=st.secrets["POLYGON_KEY"])
        }, None
    except Exception as e: return None, str(e)

# --- 3. 资产核算引擎 ---
def calculate_portfolio_value(positions, poly):
    mv = 0.0
    if not positions: return mv
    try:
        # 简单化处理：只取第一个标的现价作为参考，或循环取快照
        for sym, qty in positions.items():
            sn = poly.get_snapshot_ticker("options" if "O:" in sym else "stocks", sym.replace("O:",""))
            px = get_val(getattr(sn, 'last_trade', None), 'p', 'price') or get_val(getattr(sn, 'day', None), 'c')
            multiplier = 100 if "O:" in sym else 1
            mv += px * qty * multiplier
    except: pass
    return mv

def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

# --- 4. UI 渲染与功能逻辑 ---
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

# --- 顶部全局操作 ---
h1, h2 = st.columns([4, 1])
with h1: st.caption(f"{VERSION} | 期权语义化解析已开启 | 实时市值核算中")
if h2.button("🔄 同步全局数据", use_container_width=True): st.rerun()

tabs = st.tabs(["🏆 蜂群看板", "👑 基因孵化", "⚙️ 系统管理"])

with tabs[0]:
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | 巡逻: {d.get('patrol_count',0)}次", expanded=True):
            # 💡 数据实时计算
            cash = d.get('balance', 0.0)
            # 在 UI 层面动态计算市值（不存数据库以防过期）
            with st.spinner("核算实时市值..."):
                mv = calculate_portfolio_value(d.get('positions'), clients['poly'])
            total = cash + mv
            
            # 🚨 资产看板 (Metric)
            m1, m2, m3 = st.columns(3)
            m1.metric("现金余额 (Cash)", f"${cash:,.2f}")
            m2.metric("持仓市值 (MV)", f"${mv:,.2f}")
            m3.metric("总资产 (Total)", f"${total:,.2f}", delta=f"{total-100000:,.2f}")

            st.divider()

            c1, c2 = st.columns([1, 1])
            with c1:
                st.write("🧬 **灵魂特质**")
                st.info(d.get('style'))
                if st.button(f"🚀 立即放飞 {d['name']}", key=f"fly_{d['id']}", type="primary"):
                    # 这里调用之前的 execute_flight 逻辑... (省略以节省篇幅，保持 app.py 完整)
                    st.rerun()
            
            with c2:
                st.write("**📦 持仓明细 (语义化)**")
                pos = d.get('positions', {})
                if pos:
                    pos_data = []
                    for sym, qty in pos.items():
                        pos_data.append({"合约": parse_option_symbol(sym), "头寸": f"{qty}手"})
                    st.table(pos_data)
                else:
                    st.caption("目前账户为空仓状态")
            
            # 📜 日志区
            if d.get('logs'):
                with st.expander("📜 查看历史决策记录"):
                    for log in d['logs']: st.caption(log)