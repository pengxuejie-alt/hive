import streamlit as st
import json, time, os, random, re
import pandas as pd
from datetime import datetime
from supabase import create_client
from google import genai 
from polygon import RESTClient

# --- 1. 全局配置 ---
VERSION = "v10.3 (Synchronous Penetration)"
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

# --- 3. 🚨 核心：同步取价函数 (Debug 模式) ---
def get_verified_price(poly, symbol):
    # 强制加上 O: 协议头（如果没有）
    ticker = symbol if symbol.startswith("O:") else f"O:{symbol}"
    try:
        # 💡 这里是关键：必须区分 options 路径
        sn = poly.get_snapshot_ticker("options", ticker.replace("O:", ""))
        
        # 优先级逻辑
        lt = getattr(sn, 'last_trade', None)
        lq = getattr(sn, 'last_quote', None)
        day = getattr(sn, 'day', None)
        
        # 尝试成交价 -> 尝试买卖价中值 -> 尝试当日收盘价
        price = get_val(lt, 'p', 'price') 
        if price <= 0:
            bid, ask = get_val(lq, 'p', 'bid'), get_val(lq, 'P', 'ask')
            if bid > 0 and ask > 0: price = (bid + ask) / 2
        if price <= 0:
            price = get_val(day, 'c', 'close')
            
        return price
    except Exception as e:
        st.sidebar.error(f"Ticker {ticker} 取价失败: {e}")
        return 0.0

# --- 4. 渲染逻辑 ---
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

tabs = st.tabs(["🏆 蜂群看板", "👑 基因孵化", "⚙️ 系统管理"])

with tabs[0]:
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | 巡逻: {d.get('patrol_count',0)}次", expanded=True):
            cash = float(d.get('balance', 0.0))
            pos = d.get('positions', {})
            mv_total = 0.0
            pos_table = []
            
            # 🚨 这里的逻辑改写：确保对每一个持仓发起真实请求
            if pos:
                st.write("🔍 **持仓资产实时穿透中...**")
                for sym, qty in pos.items():
                    # 这里会触发明显的等待感，说明请求发出了
                    with st.spinner(f"正在抓取 {sym} 实时行情..."):
                        unit_px = get_verified_price(clients['poly'], sym)
                        multiplier = 100 if sym.startswith("O:") else 1
                        item_mv = unit_px * qty * multiplier
                        mv_total += item_mv
                        pos_table.append({
                            "合约": parse_option_symbol(sym),
                            "数量": f"{qty} 手",
                            "当前估价": f"${unit_px:.4f}",
                            "估值": f"${item_mv:,.2f}"
                        })

            total_assets = cash + mv_total
            pnl_pct = ((total_assets / 100000.0) - 1) * 100

            m1, m2, m3 = st.columns(3)
            m1.metric("现金余额 (Cash)", f"${cash:,.2f}")
            m2.metric("持仓估值 (Market Value)", f"${mv_total:,.2f}")
            m3.metric("总资产 (Total Assets)", f"${total_assets:,.2f}", delta=f"{pnl_pct:.2f}%")

            st.divider()
            # ... 其余 UI 保持不变
            if pos_table:
                st.table(pos_table)