import streamlit as st
import json, time, os, random, re
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai 
from polygon import RESTClient

# --- 1. 全局配置 ---
VERSION = "v9.8 (Portfolio Fix)"
st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

# --- 2. 核心辅助：解析期权代码 ---
def parse_option_symbol(symbol):
    if not symbol.startswith("O:"): return symbol
    match = re.match(r"O:([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d+)", symbol)
    if match:
        tk, yy, mm, dd, cp, strike = match.groups()
        strike_val = int(strike) / 1000
        type_str = "认涨(Call)" if cp == "C" else "认沽(Put)"
        return f"{tk} {mm}/{dd} ${strike_val} {type_str}"
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

def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

# --- 3. 实时市值核算引擎 (暴力修正版) ---
def get_realtime_market_value(positions, poly):
    mv = 0.0
    if not positions: return 0.0
    for sym, qty in positions.items():
        try:
            # 区分期权与现货路径
            if sym.startswith("O:"):
                # 💡 修正点：期权快照需去掉 O: 前缀
                opt_tk = sym.replace("O:", "")
                sn = poly.get_snapshot_ticker("options", opt_tk)
                # 优先级：最新成交价 > 昨日收盘价
                price = get_val(getattr(sn, 'last_trade', None), 'p', 'price') or \
                        get_val(getattr(sn, 'day', None), 'c') or 0.0
                mv += price * qty * 100
            else:
                sn = poly.get_snapshot_ticker("stocks", sym)
                price = get_val(getattr(sn, 'last_trade', None), 'p', 'price') or \
                        get_val(getattr(sn, 'day', None), 'c') or 0.0
                mv += price * qty
        except: continue
    return mv

# --- 4. UI 渲染 ---
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

# (放飞逻辑 execute_flight 保持 v9.7 稳定版不变...)

tabs = st.tabs(["🏆 蜂群看板", "👑 基因孵化", "⚙️ 系统管理"])

with tabs[0]:
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | 巡逻: {d.get('patrol_count',0)}次", expanded=True):
            # 💡 实时计算：不再显示 0
            cash = d.get('balance', 0.0)
            with st.spinner(f"正在穿透行情核算 {d['name']} 的资产..."):
                market_value = get_realtime_market_value(d.get('positions'), clients['poly'])
            
            total_assets = cash + market_value
            pnl = total_assets - 100000.0
            pnl_pct = (pnl / 100000.0) * 100

            # 🚨 修正后的资产看板
            m1, m2, m3 = st.columns(3)
            m1.metric("现金余额 (Cash)", f"${cash:,.2f}")
            m2.metric("持仓市值 (Market Value)", f"${market_value:,.2f}")
            # delta 显示相对于初始资金的盈亏
            m3.metric("总资产 (Total Assets)", f"${total_assets:,.2f}", delta=f"{pnl_pct:.2f}%")

            st.divider()
            
            c1, c2 = st.columns([1, 1])
            with c1:
                st.write("🧬 **灵魂特质**")
                st.info(d.get('style'))
                if st.button(f"🚀 放飞 {d['name']}", key=f"f_{d['id']}", type="primary"):
                    # 执行放飞逻辑...
                    st.rerun()
            
            with c2:
                st.write("**📦 持仓明细 (Real-time)**")
                pos = d.get('positions', {})
                if pos:
                    # 构建更友好的表格
                    table_rows = []
                    for sym, qty in pos.items():
                        table_rows.append({
                            "合约": parse_option_symbol(sym),
                            "数量": f"{qty} 手"
                        })
                    st.table(table_rows)
                else:
                    st.caption("暂无持仓")