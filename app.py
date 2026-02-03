import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json
import requests
from datetime import datetime, timezone
import pytz
from polygon import RESTClient

# --- 1. 基础配置与初始化 ---
st.set_page_config(page_title="Hive 蜂巢控制台", layout="wide", page_icon="🐝")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel("gemini-3-flash-preview")
    poly_client = RESTClient(api_key=st.secrets["POLYGON_KEY"])
except Exception as e:
    st.error(f"系统启动失败: {e}")
    st.stop()

# --- 2. 估值函数 (增加缓存防止压力过大) ---
@st.cache_data(ttl=60)
def get_valuation(positions):
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
            details.append({"代码": k, "仓位": v, "价格": f"${p:.2f}", "市值": f"${val:,.2f}"})
        except:
            details.append({"代码": k, "仓位": v, "价格": "获取中", "市值": "0.00"})
    return mv, details

# --- 3. UI 布局 ---
with st.sidebar:
    st.title("🐝 Hive 蜂巢")
    if st.button("🚀 放飞所有工蜂"):
        repo = st.secrets["GITHUB_REPO"]
        requests.post(f"https://api.github.com/repos/{repo}/actions/workflows/hive_cycle.yml/dispatches",
                      headers={"Authorization": f"token {st.secrets['GITHUB_TOKEN']}"}, json={"ref": "main"})
        st.success("巡检指令已下达")

# 明确定义三个 Tag，确保即使内容出错结构也不消失
t1, t2, t3 = st.tabs(["🏆 工蜂列表", "👑 蜂后孵化", "⚙️ 系统管理"])

# --- TAB 1: 工蜂列表 ---
with t1:
    res = supabase.table("drones").select("*").execute()
    if not res.data:
        st.info("蜂巢目前是空的，请前往孵化。")
    else:
        for d in res.data:
            # 计算年龄
            created_at = datetime.fromisoformat(d.get('created_at', datetime.now(timezone.utc).isoformat()).replace('Z', '+00:00'))
            age_h = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
            
            # 计算资产
            cash = float(d.get('balance', 10000.0))
            mv, pos_list = get_valuation(d.get('positions', {}))
            
            with st.expander(f"🐝 {d['name']} | 资产总值: ${cash + mv:,.2f} | 年龄: {age_h:.1f}h"):
                c1, c2, c3 = st.columns(3)
                c1.metric("巡检次数", f"{d.get('patrol_count', 0)}次")
                c2.metric("可用现金", f"${cash:,.2f}")
                c3.metric("性格", d.get('persona', '未知'))
                
                st.write(f"🔍 **监控标的:** {', '.join(d.get('portfolio', []))}")
                if pos_list: st.table(pd.DataFrame(pos_list))
                
                st.write("**📜 最新日志:**")
                for log in (d.get('logs', []) or [])[:5]:
                    st.caption(log)

# --- TAB 2: 蜂后孵化 ---
with t2:
    st.subheader("🧬 基因编码：孵化新工蜂")
    instruction = st.text_area("输入孵化指令:", height=150)
    if st.button("注入基因并孵化", type="primary"):
        with st.spinner("蜂后编码中..."):
            try:
                p = f"设计工蜂。返回纯JSON列表：[{{'name':'代号','focus':'option','portfolio':['代码'],'logic':'逻辑','persona':'性格','balance':10000,'initial_balance':10000,'memory':'等待开盘'}}]。指令：{instruction}"
                r = queen_ai.generate_content(p)
                items = json.loads(r.text.strip().replace("```json", "").replace("```", "").strip())
                for item in items:
                    item['created_at'] = datetime.now(timezone.utc).isoformat()
                    item['patrol_count'] = 0
                    supabase.table("drones").insert(item).execute()
                st.success("孵化成功！"); st.rerun()
            except Exception as e: st.error(f"孵化失败: {e}")

# --- TAB 3: 系统管理 (三种重置选项) ---
with t3:
    st.header("⚙️ 蜂巢核心维护")
    
    st.subheader("1. 文明重启（全量重置）")
    st.caption("重置出生时间、巡检次数、账本、日志、记忆。让工蜂如同刚孵化一般。")
    if st.button("🩹 执行文明重启", key="reset_all_full"):
        supabase.table("drones").update({
            "balance": 10000.0,
            "positions": {},
            "peak_balance": 10000.0,
            "logs": [],
            "memory": "等待开盘",
            "patrol_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).neq("id", -1).execute()
        st.success("所有工蜂已全量重置。")
        st.rerun()

    st.divider()

    st.subheader("2. 财务审计（资产重置）")
    st.caption("重置账本、日志；保留出生时间、巡检次数、记忆。适合纠正交易错误但保留经验。")
    if st.button("🩹 执行财务审计", key="reset_finance_only"):
        supabase.table("drones").update({
            "balance": 10000.0,
            "positions": {},
            "peak_balance": 10000.0,
            "logs": []
        }).neq("id", -1).execute()
        st.success("账本与日志已清空，工蜂经验已保留。")
        st.rerun()

    st.divider()

    st.subheader("3. 蜂巢清理（全量删除）")
    st.caption("彻底从数据库删除所有工蜂数据。")
    if st.button("🔥 执行全量删除", type="primary"):
        if st.checkbox("我确认要删除所有工蜂数据"):
            supabase.table("drones").delete().neq("id", -1).execute()
            st.success("蜂巢已清空。")
            st.rerun()