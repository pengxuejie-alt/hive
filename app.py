import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json
from datetime import datetime
import pytz
from polygon import RESTClient

# --- 核心初始化 ---
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
poly_client = RESTClient(api_key=st.secrets["POLYGON_KEY"])

def draw_drone_card(d, icon):
    """渲染单只蜜蜂卡片并包含‘单体修复’按钮"""
    with st.expander(f"{icon} {d['name']} | 资产: ${d['total_assets']:,.2f}"):
        st.write(f"**🧠 经验记录:** {d.get('memory', '学习中...')}")
        
        c1, c2 = st.columns(2)
        # 单体重置按钮
        if c1.button(f"🩹 修复该蜂账本", key=f"reset_{d['id']}"):
            supabase.table("drones").update({
                "balance": 10000.0, 
                "positions": {}, 
                "peak_balance": 10000.0
            }).eq("id", d["id"]).execute()
            st.success(f"{d['name']} 已重置！")
            st.rerun()
        
        if c2.button(f"🗑️ 淘汰", key=f"del_{d['id']}"):
            supabase.table("drones").delete().eq("id", d["id"]).execute()
            st.rerun()

# --- 主界面 ---
st.title("🐝 Hive 蜂巢管理后台")
tabs = st.tabs(["🏆 演化排行榜", "⚙️ 系统维护"])

with tabs[0]:
    # 此处省略数据获取逻辑，调用 draw_drone_card(d, icon)
    st.write("展示蜜蜂列表...")

with tabs[1]:
    st.header("🛠️ 全局管理")
    
    # --- 核心功能：全体一键重置 ---
    st.warning("此操作将重置所有兵蜂的金额为 $10,000，清空所有持仓，但会保留它们的 Memory (记忆)。")
    if st.button("🩹 一键重置全体账本 (保留记忆)", type="primary"):
        try:
            # neq("id", -1) 是为了匹配所有有效 ID 的通用写法
            supabase.table("drones").update({
                "balance": 10000.0,
                "positions": {},
                "peak_balance": 10000.0
            }).neq("id", -1).execute()
            st.success("全体账本已完成一键修复！")
            st.rerun()
        except Exception as e:
            st.error(f"重置失败: {e}")

    st.divider()
    if st.button("🔥 全体大灭绝 (清空数据库)"):
        supabase.table("drones").delete().neq("id", -1).execute()
        st.rerun()