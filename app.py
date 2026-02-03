import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json
import requests
from datetime import datetime
import pytz
from polygon import RESTClient

# --- 1. 基础配置与初始化 ---
st.set_page_config(page_title="Hive | 虎之眼演化实验室", layout="wide", page_icon="🐝")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel("gemini-3-flash-preview")
    poly_client = RESTClient(api_key=st.secrets["POLYGON_KEY"])
except Exception as e:
    st.error(f"系统启动失败，请检查 Secrets: {e}")
    st.stop()

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
    """资产估值：即使 Polygon 报错也不中断 UI 渲染"""
    mv = 0.0
    details = []
    if not positions: return 0.0, []
    for k, v in positions.items():
        try:
            if k.startswith("O:"):
                # 处理期权逻辑
                p = poly_client.get_last_trade(k).price
                val = float(v) * float(p) * 100
            else:
                # 处理股票逻辑
                p = poly_client.get_snapshot_ticker("stocks", k).last_trade.p
                val = float(v) * float(p)
            mv += val
            details.append({"代码": k, "仓位": v, "价格": f"${p:.2f}", "市值": f"${val:.2f}"})
        except:
            details.append({"代码": k, "仓位": v, "价格": "获取中", "市值": "0.00"})
    return mv, details

# --- 3. UI 布局与侧边栏 ---
with st.sidebar:
    st.header("🕒 控制台")
    st.write(f"ET: {datetime.now(pytz.timezone('US/Eastern')).strftime('%H:%M:%S')}")
    # 修正语法错误：添加了括号调用和冒号
    if st.button("🚀 手动起飞巡检"):
        if trigger_action():
            st.success("GitHub 指令已送达")
        else:
            st.error("起飞失败")
    st.divider()

# 显式定义 3 个标签页，增强 UI 稳定性
t1, t2, t3 = st.tabs(["🏆 兵蜂列表", "👑 蜂后孵化", "⚙️ 系统维护"])

# --- TAB 1: 兵蜂实战列表 (含单体修复) ---
with t1:
    res = supabase.table("drones").select("*").execute()
    if not res.data:
        st.info("蜂巢暂无工蜂。")
    else:
        for d in res.data:
            cash = float(d.get('balance', 10000.0))
            mkt_val, pos_list = get_valuation(d.get('positions', {}))
            
            with st.expander(f"🐝 {d['name']} | 总资产: ${cash + mkt_val:,.2f}"):
                if pos_list: st.table(pd.DataFrame(pos_list))
                st.info(f"**🧠 经验记录:** {d.get('memory', '学习中...')}")
                
                # 手术区：单体修复
                c1, c2 = st.columns(2)
                if c1.button(f"🩹 修复此蜂账本", key=f"fix_{d['id']}"):
                    supabase.table("drones").update({"balance":10000.0, "positions":{}, "peak_balance":10000.0}).eq("id", d["id"]).execute()
                    st.rerun()
                if c2.button(f"🗑️ 淘汰", key=f"del_{d['id']}"):
                    supabase.table("drones").delete().eq("id", d["id"]).execute()
                    st.rerun()

# --- TAB 2: 蜂后孵化 ---
with t2:
    st.subheader("🧬 基因注入")
    instruction = st.text_area("孵化指令:", height=100)
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

# --- TAB 3: 全局维护 ---
with t3:
    st.header("⚙️ 蜂巢底层维护")
    if st.button("🩹 一键重置全体账本 (保留记忆)", type="primary"):
        supabase.table("drones").update({"balance":10000.0, "positions":{}, "peak_balance":10000.0}).neq("id", -1).execute()
        st.success("全体校准已完成！")
        st.rerun()