import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# --- 1. 初始化 ---
VERSION = "v11.6 (Force Re-sequencing)"
st.set_page_config(page_title="Hive 智能金融", layout="wide")

@st.cache_resource
def init_hive_engine():
    try:
        return {
            "supabase": create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]),
            "gen_client": genai.Client(api_key=st.secrets["GEMINI_KEY"]),
            "poly": RESTClient(api_key=st.secrets["POLYGON_KEY"])
        }, None
    except Exception as e: return None, str(e)

cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

# --- 2. 核心辅助函数 ---
def parse_option_symbol(symbol):
    if not symbol.startswith("O:"): return symbol
    match = re.match(r"O:([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d+)", symbol)
    if match:
        tk, yy, mm, dd, cp, strike = match.groups()
        strike_val = int(strike) / 1000
        return f"{tk} {mm}/{dd} ${strike_val} {'Call' if cp == 'C' else 'Put'}"
    return symbol

def get_verified_price(poly, symbol):
    ticker = symbol if symbol.startswith("O:") else f"O:{symbol}"
    try:
        end = datetime.now()
        start = end - timedelta(days=3)
        aggs = poly.get_aggs(ticker, 1, "minute", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if aggs: return float(aggs[-1].close)
        daily = poly.get_aggs(ticker, 1, "day", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        return float(daily[-1].close) if daily else 0.01
    except: return 0.01

def calculate_age(created_at_str):
    try:
        created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
        delta = datetime.now(pytz.UTC) - created_at
        if delta.days > 0: return f"{delta.days}天 {delta.seconds // 3600}小时"
        return f"{delta.seconds // 3600}小时"
    except: return "刚刚诞生"

# --- 3. 页面渲染 ---
st.title("🐝 Hive 智能金融蜂群")
tabs = st.tabs(["🏆 蜂群看板", "👑 DNA 孵化器", "⚙️ 管理"])

with tabs[0]:
    d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | 状态: 活跃", expanded=True):
            # 资产核算 (保持穿透)
            cash = float(d.get('balance', 100000.0))
            pos = d.get('positions', {})
            mv_total = 0.0
            pos_table = []
            if pos:
                for sym, qty in pos.items():
                    px = get_verified_price(clients['poly'], sym)
                    mv = px * qty * (100 if "O:" in sym else 1)
                    mv_total += mv
                    pos_table.append({"合约": parse_option_symbol(sym), "数量": f"{qty}手", "单价": f"${px:.2f}", "市值": f"${mv:,.2f}"})

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("现金 (Cash)", f"${cash:,.2f}")
            m2.metric("持仓市值", f"${mv_total:,.2f}")
            m3.metric("总资产", f"${cash + mv_total:,.2f}", delta=f"{((cash + mv_total)/100000-1)*100:.2f}%")
            m4.metric("存活年龄", calculate_age(d.get('created_at')))

            st.divider()

            # --- 🧬 DNA 核心区域 (修复按钮缺失) ---
            st.write("🧬 **DNA 特征片段 (Genetic Fragments)**")
            dna_raw = d.get('style', '')
            
            # 第一行：展示 DNA 内容
            if " | " in dna_raw:
                frags = dna_raw.split(' | ')
                cols = st.columns(len(frags))
                for i, f in enumerate(frags): cols[i].code(f)
            else:
                st.info(f"原始基因描述: {dna_raw}")
            
            # 第二行：放置功能按钮
            c_btn1, c_btn2, _ = st.columns([1, 1, 2])
            if c_btn1.button("🧬 基因重组", key=f"re_{d['id']}", type="secondary", use_container_width=True):
                with st.spinner("正在提取显性特征..."):
                    p = f"将这段描述重构为 3-5 个用 ' | ' 分隔的 '特征:短语'，严禁长句。内容：{dna_raw}"
                    new_dna = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=p).text.strip()
                    clients['supabase'].table("drones").update({"style": new_dna}).eq("id", d["id"]).execute()
                    st.rerun()
            
            st.divider()

            # 记忆与持仓
            c1, c2 = st.columns([1, 1.5])
            with c1:
                st.write("🧠 **长期记忆 (Memory)**")
                with st.container(height=200):
                    for l in (d.get('logs') or []): st.caption(f"• {l}")
                if st.button(f"🚀 单独放飞 {d['name']}", key=f"f_{d['id']}", type="primary", use_container_width=True):
                    # 此处调用之前的放飞逻辑 execute_flight_v11
                    st.rerun()
            with c2:
                st.write("**📦 实盘持仓明细**")
                if pos_table: st.table(pos_table)
                else: st.caption("空仓状态")