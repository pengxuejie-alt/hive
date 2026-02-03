import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json
import requests
from datetime import datetime
import pytz
from polygon import RESTClient

# --- 1. 初始化 ---
st.set_page_config(page_title="Hive | 虎之眼演化实验室", layout="wide", page_icon="🐝")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel("gemini-3-flash-preview")
    poly_client = RESTClient(api_key=st.secrets["POLYGON_KEY"])
except Exception as e:
    st.error(f"初始化失败: {e}")
    st.stop()

# --- 2. 核心功能 ---
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
    """资产估值：报错不中断渲染"""
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
            details.append({"代码": k, "仓位": v, "价格": "获取中", "市值": "0.00"})
    return mv, details

# --- 3. UI 布局 ---
with st.sidebar:
    st.header("🕒 系统时钟")
    st.write(f"ET: {datetime.now(pytz.timezone('US/Eastern')).strftime('%H:%M:%S')}")
    # 修正语法错误处：添加了括号和冒号
    if st.button("🚀 手动起飞巡检"):
        if trigger_action():
            st.success("已发送 GitHub 指令")
        else:
            st.error("发送失败")

# 强制定义 3 个标签页
tabs = st.tabs(["🏆 兵蜂列表", "👑 蜂后孵化", "⚙️ 全局维护"])

# --- TAB 1: 兵蜂实战列表 ---
with tabs[0]:
    res = supabase.table("drones").select("*").execute()
    if not res.data:
        st.info("蜂巢暂无工蜂。")
    else:
        for d in res.data:
            cash = float(d.get('balance', 10000.0))
            mkt_val, pos_list = get_valuation(d.get('positions', {}))
            
            with st.expander(f"🐝 {d['name']} | 总资产: ${cash + mkt_val:,.2f}"):
                if pos_list: st.table(pd.DataFrame(pos_list))
                st.info(f"**🧠 经验记忆:** {d.get('memory', '学习中...')}")
                
                c1, c2 = st.columns(2)
                # 单体修复：精准重置账本，保留记忆
                if c1.button(f"🩹 修复此蜂账本", key=f"btn_fix_{d['id']}"):
                    supabase.table("drones").update({"balance":10000.0, "positions":{}, "peak_balance":10000.0}).eq("id", d["id"]).execute()
                    st.rerun()
                if c2.button(f"🗑️ 淘汰", key=f"btn_del_{d['id']}"):
                    supabase.table("drones").delete().eq("id", d["id"]).execute()
                    st.rerun()

# --- TAB 2: 蜂后孵化 ---
with tabs[1]:
    st.subheader("🧬 注入新基因")
    instruction = st.text_area("输入孵化指令:", height=100)
    if st.button("开始孵化", type="primary"):
        with st.spinner("蜂后编码中..."):
            try:
                p = f"设计兵蜂。返回纯JSON列表：[{{'name':'代号','focus':'option','portfolio':['代码'],'logic':'逻辑','persona':'性格','balance':10000,'initial_balance':10000,'memory':'等待开盘'}}]。指令：{instruction}"
                r = queen_ai.generate_content(p)
                items = json.loads(r.text.strip().replace("```json", "").replace("```", "").strip())
                for item in items:
                    item['peak_balance'] = 10000.0
                    supabase.table("drones").insert(item).execute()
                st.success("孵化成功！"); st.rerun()
            except Exception as e: st.error(f"孵化失败: {e}")

# --- TAB 3: 系统维护 ---
with tabs[2]:
    st.subheader("⚙️ 蜂巢维护")
    if st.button("🩹 一键重置全体账本 (保留记忆)", type="primary"):
        supabase.table("drones").update({"balance":10000.0, "positions":{}, "peak_balance":10000.0}).neq("id", -1).execute()
        st.success("全体校准完成！"); st.rerun()