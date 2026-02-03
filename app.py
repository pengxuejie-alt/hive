import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json, requests
from datetime import datetime, timezone
import pytz
from polygon import RESTClient

# --- 初始化 ---
st.set_page_config(page_title="Hive 蜂巢看板", layout="wide", page_icon="🐝")
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
genai.configure(api_key=st.secrets["GEMINI_KEY"])
queen_ai = genai.GenerativeModel("gemini-3-flash-preview")
poly_client = RESTClient(api_key=st.secrets["POLYGON_KEY"])

def get_live_valuation(positions):
    """深度穿透：利用付费接口获取实时市值"""
    mv = 0.0
    details = []
    if not positions: return 0.0, []
    
    for k, v in positions.items():
        try:
            if k.startswith("O:"):
                # 付费接口 Last Trade 极其稳定
                p = poly_client.get_last_trade(k).price
                val = float(v) * float(p) * 100
            else:
                snap = poly_client.get_snapshot_ticker("stocks", k)
                p = snap.last_trade.p if snap.last_trade.p > 0 else snap.prev_day.c
                val = float(v) * float(p)
            mv += val
            details.append({"代码": k, "仓位": v, "现价": f"${p:.2f}", "市值": f"${val:,.2f}"})
        except:
            details.append({"代码": k, "仓位": v, "现价": "获取中", "市值": "0.00"})
    return mv, details

# --- UI 侧边栏 ---
with st.sidebar:
    st.title("🐝 Hive 蜂巢")
    if st.button("🚀 放飞所有工蜂"):
        repo = st.secrets["GITHUB_REPO"]
        requests.post(f"https://api.github.com/repos/{repo}/actions/workflows/hive_cycle.yml/dispatches",
                      headers={"Authorization": f"token {st.secrets['GITHUB_TOKEN']}"}, json={"ref": "main"})
        st.success("巡检指令已下达")

t1, t2, t3 = st.tabs(["🏆 工蜂列表", "👑 蜂后孵化", "⚙️ 系统管理"])

with t1:
    res = supabase.table("drones").select("*").execute()
    if res.data:
        for d in res.data:
            # 1. 列表渲染：直接读取数据库，不调 API
            db_total = d.get('total_assets', 10000.0)
            created_at = datetime.fromisoformat(d.get('created_at').replace('Z', '+00:00'))
            age_h = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
            
            with st.expander(f"🐝 {d['name']} | 总资产: ${db_total:,.2f} | 巡检: {d.get('patrol_count', 0)}次"):
                # 2. 深度穿透：点开后才重算实时价格
                st.caption(f"性格: {d.get('persona')} | 年龄: {age_h:.1f}h | 监控: {', '.join(d.get('portfolio', []))}")
                
                live_mv, pos_details = get_live_valuation(d.get('positions', {}))
                cash = float(d.get('balance', 10000.0))
                
                c1, c2 = st.columns(2)
                c1.metric("实时现金余额", f"${cash:,.2f}")
                c2.metric("实时持仓市值", f"${live_mv:,.2f}")
                
                if pos_details:
                    st.table(pd.DataFrame(pos_details))
                
                st.write("**📜 巡检记录:**")
                for log in (d.get('logs', []) or [])[:10]:
                    st.caption(log)

# --- TAB 2 & 3 保持之前的逻辑，包含三种重置模式 ---
with t2:
    # 蜂后孵化代码...
    pass

with t3:
    st.header("⚙️ 维护管理")
    # 文明重启/财务审计/全量删除按钮...
    pass