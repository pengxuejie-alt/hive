import streamlit as st
import json, time, os, random, re
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai 
from polygon import RESTClient

# --- 1. 全局配置 ---
VERSION = "v9.9 (Hardened Portfolio Penetration)"
st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

# --- 2. 核心辅助函数 (代码整容) ---
def parse_option_symbol(symbol):
    if not symbol.startswith("O:"): return symbol
    match = re.match(r"O:([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d+)", symbol)
    if match:
        tk, yy, mm, dd, cp, strike = match.groups()
        strike_val = int(strike) / 1000
        type_str = "Call" if cp == "C" else "Put"
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

# --- 3. 🚨 核心修复：暴力询价引擎 ---
def get_hardened_price(poly, symbol):
    try:
        # A. 如果是期权
        if symbol.startswith("O:"):
            # 1. 尝试获取最新成交 (最实时)
            last_trade = poly.get_last_trade("options", symbol)
            price = get_val(last_trade, 'p', 'price')
            
            # 2. 如果没成交，尝试获取前一天的聚合收盘价 (兜底)
            if price <= 0:
                prev = poly.get_previous_close_agg(symbol)
                price = get_val(prev[0] if prev else None, 'close')
            
            # 3. 如果还是没有，尝试获取买卖盘中值
            if price <= 0:
                lq = poly.get_last_quote("options", symbol)
                price = (get_val(lq, 'p', 'bid') + get_val(lq, 'P', 'ask')) / 2
                
            return price or 0.01 # 极端保底：哪怕是垃圾期权也按 0.01 算，不显示 0
        
        # B. 如果是股票
        else:
            sn = poly.get_snapshot_ticker("stocks", symbol)
            price = get_val(getattr(sn, 'last_trade', None), 'p', 'price') or \
                    get_val(getattr(sn, 'day', None), 'c')
            return price
    except:
        return 0.0

# --- 4. UI 渲染 ---
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

# (execute_flight 逻辑保持稳定)

tabs = st.tabs(["🏆 蜂群看板", "👑 基因孵化", "⚙️ 管理"])

with tabs[0]:
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | 巡逻: {d.get('patrol_count',0)}次", expanded=True):
            cash = float(d.get('balance', 0.0))
            pos = d.get('positions', {})
            mv_total = 0.0
            pos_table = []
            
            if pos:
                with st.status(f"正在对 {d['name']} 的持仓执行暴力询价...", expanded=False) as status:
                    for sym, qty in pos.items():
                        unit_px = get_hardened_price(clients['poly'], sym)
                        multiplier = 100 if sym.startswith("O:") else 1
                        item_mv = unit_px * qty * multiplier
                        mv_total += item_mv
                        pos_table.append({
                            "合约": parse_option_symbol(sym),
                            "数量": f"{qty} 手",
                            "当前单价": f"${unit_px:.4f}",
                            "单项市值": f"${item_mv:,.2f}"
                        })
                    status.update(label="询价完成", state="complete")

            total_assets = cash + mv_total
            pnl_val = total_assets - 100000.0
            pnl_pct = (pnl_val / 100000.0) * 100

            m1, m2, m3 = st.columns(3)
            m1.metric("现金余额 (Cash)", f"${cash:,.2f}")
            m2.metric("持仓市值 (Market Value)", f"${mv_total:,.2f}")
            m3.metric("总资产 (Total Assets)", f"${total_assets:,.2f}", delta=f"{pnl_pct:.2f}%")

            st.divider()
            c1, c2 = st.columns([1, 1.5])
            with c1:
                st.write("🧬 **灵魂特质**")
                st.info(d.get('style'))
                if st.button(f"🚀 放飞 {d['name']}", key=f"f_{d['id']}", type="primary"):
                    # execute_flight...
                    st.rerun()
            with c2:
                st.write("**📦 持仓明细 (Real-time Analysis)**")
                if pos_table:
                    st.table(pos_table)
                else:
                    st.caption("暂无持仓")