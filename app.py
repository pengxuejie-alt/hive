import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# --- 1. 全局配置 ---
VERSION = "v10.7 (Memory Palace)"
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

def calculate_age(created_at_str):
    try:
        created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
        now = datetime.now(pytz.UTC)
        delta = now - created_at
        if delta.days > 0: return f"{delta.days}天 {delta.seconds // 3600}小时"
        return f"{delta.seconds // 3600}小时"
    except: return "刚刚诞生"

# --- 3. 实时穿透取价 ---
def get_verified_price_v4(poly, symbol):
    ticker = symbol if symbol.startswith("O:") else f"O:{symbol}"
    try:
        end = datetime.now()
        start = end - timedelta(days=3)
        aggs = poly.get_aggs(ticker, 1, "minute", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if aggs: return float(aggs[-1].close)
        daily_aggs = poly.get_aggs(ticker, 1, "day", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        return float(daily_aggs[-1].close) if daily_aggs else 0.01
    except: return 0.01

# --- 4. 初始化 ---
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

# --- 5. UI 渲染 ---
tabs = st.tabs(["🏆 蜂群看板", "👑 基因孵化", "⚙️ 管理"])

with tabs[0]:
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | 存活: {calculate_age(d.get('created_at'))} | 巡逻: {d.get('patrol_count',0)}次", expanded=True):
            # 💰 资产核算
            cash = float(d.get('balance', 0.0))
            pos = d.get('positions', {})
            mv_total = 0.0
            pos_table = []
            
            if pos:
                for sym, qty in pos.items():
                    unit_px = get_verified_price_v4(clients['poly'], sym)
                    item_mv = unit_px * qty * (100 if sym.startswith("O:") else 1)
                    mv_total += item_mv
                    pos_table.append({"合约": parse_option_symbol(sym), "数量": f"{qty} 手", "单价": f"${unit_px:.4f}", "市值": f"${item_mv:,.2f}"})

            total_assets = cash + mv_total
            pnl_pct = ((total_assets / 100000.0) - 1) * 100

            # 顶部资产卡片
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("现金", f"${cash:,.2f}")
            m2.metric("持仓市值", f"${mv_total:,.2f}")
            m3.metric("总资产", f"${total_assets:,.2f}", delta=f"{pnl_pct:.2f}%")
            m4.metric("记忆深度", f"{len(d.get('logs') or [])} 条")

            st.divider()
            
            # 核心内容区
            c1, c2 = st.columns([1, 1.5])
            with c1:
                st.write("🧬 **灵魂特质 (Persona)**")
                st.info(d.get('style', '未载入灵魂特质'))
                
                # --- 🧠 记忆展示区 ---
                st.write("📜 **长期记忆 (Memory Logs)**")
                memory_logs = d.get('logs') or []
                if memory_logs:
                    with st.container(height=250): # 增加滚动容器
                        for log in memory_logs:
                            st.caption(f"🔘 {log}")
                else:
                    st.caption("暂无历史记忆...")
                
                if st.button(f"🚀 放飞 {d['name']}", key=f"f_{d['id']}", type="primary", use_container_width=True):
                    st.rerun()
            
            with c2:
                st.write("**📦 实盘持仓明细**")
                if pos_table: st.table(pos_table)
                else: st.caption("目前账户为空仓状态")