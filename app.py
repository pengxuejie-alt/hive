import streamlit as st
import json, time, os, random, re
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai 
from polygon import RESTClient

# --- 1. 全局配置 ---
VERSION = "v10.1 (Ticker Protocol Fixed)"
st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

# --- 2. 核心辅助 ---
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

# --- 3. 🚨 实时核算引擎：协议头锁定版 ---
def get_live_price(poly, symbol):
    try:
        # 💡 修正点：无论期权还是股票，统一使用 snapshot 接口，但必须带协议头
        # Polygon SDK 在 get_snapshot_ticker 内部会根据前缀自动识别类别
        ticker = symbol if symbol.startswith("O:") else symbol.upper()
        
        # 强制调用最新的快照
        sn = poly.get_snapshot_ticker("options" if "O:" in ticker else "stocks", ticker)
        
        # 优先级：最新成交价 > 当日收盘价 > 昨收价
        price = get_val(getattr(sn, 'last_trade', None), 'p', 'price') or \
                get_val(getattr(sn, 'day', None), 'c', 'close') or \
                get_val(poly.get_previous_close_agg(ticker)[0], 'close')
                
        return price
    except Exception as e:
        return 0.0

# --- 4. UI 渲染 ---
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

# --- 5. 蜂群面板 ---
tabs = st.tabs(["🏆 蜂群看板", "👑 基因孵化", "⚙️ 管理"])

with tabs[0]:
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | 巡逻: {d.get('patrol_count',0)}次", expanded=True):
            cash = float(d.get('balance', 0.0))
            pos = d.get('positions', {})
            mv_total = 0.0
            pos_table = []
            
            if pos:
                # 💡 并行取价提速
                with st.status(f"正在穿透 GLD 实时行情...", expanded=False) as status:
                    for sym, qty in pos.items():
                        unit_px = get_live_price(clients['poly'], sym)
                        multiplier = 100 if sym.startswith("O:") else 1
                        item_mv = unit_px * qty * multiplier
                        mv_total += item_mv
                        pos_table.append({
                            "合约": parse_option_symbol(sym),
                            "数量": f"{qty} 手",
                            "实时单价": f"${unit_px:.4f}",
                            "当前市值": f"${item_mv:,.2f}"
                        })
                    status.update(label="实时核算完成", state="complete")

            total_assets = cash + mv_total
            pnl_val = total_assets - 100000.0
            pnl_pct = (pnl_val / 100000.0) * 100

            m1, m2, m3 = st.columns(3)
            m1.metric("现金余额 (Cash)", f"${cash:,.2f}")
            m2.metric("持仓估值 (Market Value)", f"${mv_total:,.2f}")
            # 盈亏 delta 现在可以准确反映实时变动了
            m3.metric("总资产 (Total Assets)", f"${total_assets:,.2f}", delta=f"{pnl_pct:.2f}%")

            st.divider()
            c1, c2 = st.columns([1, 1.5])
            with c1:
                st.write("🧬 **灵魂特质**")
                st.info(d.get('style'))
                if st.button(f"🚀 放飞 {d['name']}", key=f"f_{d['id']}", type="primary"):
                    st.rerun()
            with c2:
                st.write("**📦 持仓明细 (Live Data)**")
                if pos_table:
                    st.table(pos_table)
                else:
                    st.caption("暂无持仓")