import streamlit as st
import json, time, os, random, re
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# --- 1. 全局配置 ---
VERSION = "v10.4 (404 Path Fix)"
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

# --- 3. 🚨 终极核算：绕过 404 的 Aggs 取价法 ---
def get_verified_price_v4(poly, symbol):
    # 确保前缀正确
    ticker = symbol if symbol.startswith("O:") else f"O:{symbol}"
    try:
        # 💡 既然 Snapshot 报 404，我们改用 Aggregates 接口
        # 获取今天和昨天的分钟线，取最后一条
        end = datetime.now()
        start = end - timedelta(days=2)
        
        # 调用 Aggs 接口（这是 Polygon 最稳定的底层接口）
        aggs = poly.get_aggs(
            ticker, 
            1, 
            "minute", 
            start.strftime("%Y-%m-%d"), 
            end.strftime("%Y-%m-%d")
        )
        
        if aggs:
            # 取最后一条分钟线的收盘价
            return float(aggs[-1].close)
        
        # 如果分钟线没有（可能没成交），尝试日线
        daily_aggs = poly.get_aggs(
            ticker, 
            1, 
            "day", 
            start.strftime("%Y-%m-%d"), 
            end.strftime("%Y-%m-%d")
        )
        return float(daily_aggs[-1].close) if daily_aggs else 0.01
    except Exception as e:
        st.sidebar.error(f"Aggs 穿透失败 {ticker}: {e}")
        return 0.0

# --- 4. 看板布局渲染 ---
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

tabs = st.tabs(["🏆 蜂群看板", "👑 基因孵化", "⚙️ 管理"])

with tabs[0]:
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | 巡逻: {d.get('patrol_count',0)}次", expanded=True):
            cash = float(d.get('balance', 0.0))
            pos = d.get('positions', {})
            mv_total = 0.0
            pos_table = []
            
            if pos:
                st.write("🔍 **全链路穿透询价中 (Aggs Mode)...**")
                for sym, qty in pos.items():
                    with st.spinner(f"正在同步 {sym} 的 K 线数据..."):
                        unit_px = get_verified_price_v4(clients['poly'], sym)
                        multiplier = 100 if sym.startswith("O:") else 1
                        item_mv = unit_px * qty * multiplier
                        mv_total += item_mv
                        pos_table.append({
                            "合约": parse_option_symbol(sym),
                            "数量": f"{qty} 手",
                            "实时单价": f"${unit_px:.4f}",
                            "市值": f"${item_mv:,.2f}"
                        })

            total_assets = cash + mv_total
            pnl_pct = ((total_assets / 100000.0) - 1) * 100

            m1, m2, m3 = st.columns(3)
            m1.metric("现金余额 (Cash)", f"${cash:,.2f}")
            m2.metric("持仓市值 (Market Value)", f"${mv_total:,.2f}")
            m3.metric("总资产 (Total Assets)", f"${total_assets:,.2f}", delta=f"{pnl_pct:.2f}%")

            st.divider()
            if pos_table:
                st.table(pos_table)
            
            if st.button(f"🚀 放飞 {d['name']}", key=f"f_{d['id']}"):
                st.rerun()