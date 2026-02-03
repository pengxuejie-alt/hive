import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai  # 暂时保留，但加了初始化保护
import json
import requests
from datetime import datetime
import pytz
from polygon import RESTClient

# --- 1. 初始化 (容错处理) ---
st.set_page_config(page_title="Hive | 虎之眼演化实验室", layout="wide", page_icon="🐝")

@st.cache_resource
def init_clients():
    try:
        supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
        genai.configure(api_key=st.secrets["GEMINI_KEY"])
        queen_ai = genai.GenerativeModel("gemini-3-flash-preview")
        poly_client = RESTClient(api_key=st.secrets["POLYGON_KEY"])
        return supabase, queen_ai, poly_client
    except Exception as e:
        st.error(f"Secrets 配置或连接失败: {e}")
        return None, None, None

supabase, queen_ai, poly_client = init_clients()

# --- 2. 核心功能函数 ---
def trigger_action():
    try:
        token = st.secrets["GITHUB_TOKEN"].strip()
        repo = st.secrets["GITHUB_REPO"].strip()
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        url = f"https://api.github.com/repos/{repo}/actions/workflows/hive_cycle.yml/dispatches"
        res = requests.post(url, headers=headers, json={"ref": "main"})
        return res.status_code == 204
    except: return False

def get_valuation(positions):
    """手术刀级资产透视，报错不中断渲染"""
    mv = 0.0
    details = []
    if not positions: return 0.0, []
    for k, v in positions.items():
        try:
            if k.startswith("O:"):
                p = poly_client.get_last_trade(k).price
                val = float(v) * float(p) * 100
            else:
                p = poly_client.get_snapshot_ticker("stocks", k).last_trade.p
                val = float(v) * float(p)
            mv += val
            details.append({"代码": k, "仓位": v, "价格": f"${p:.2f}", "市值": f"${val:.2f}"})
        except:
            details.append({"代码": k, "仓位": v, "价格": "获取失败", "市值": "0.00"})
    return mv, details

# --- 3. UI 布局 ---
with st.sidebar:
    st.header("🕒 系统时钟")
    st.write(f"ET: {datetime.now(pytz.timezone('US/Eastern')).strftime('%H:%M:%S')}")
    if st.button("🚀 手动起飞巡检"):
        if trigger_action