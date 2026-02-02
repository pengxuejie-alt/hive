import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json

# --- 核心配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
st.set_page_config(page_title="Hive | 兵蜂崛起", layout="wide", page_icon="🐝")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel(AI_MODEL_NAME)
except Exception as e:
    st.error(f"连接失败: {e}"); st.stop()

st.title("🐝 Hive 蜂巢：自动化交易与资管系统")

t1, t2, t3 = st.tabs(["👑 蜂后孵化", "📦 实时监控", "⚙️ 系统维护"])

with t1:
    col1, col2 = st.columns([2, 1])
    with col1:
        instruction = st.text_area("蜂后指令:", placeholder="例如：孵化一个激进的兵蜂，专注NVDA期权，初始资金1万。")
    with col2:
        st.info("💡 **工蜂**：巡检、提醒、分析。\n\n⚔️ **兵蜂**：执行交易、管理仓位、追求利润。")
    
    if st.button("执行演化", type="primary"):
        with st.spinner("蜂后正在编码基因..."):
            prompt = f"你是蜂后。根据指令设计单位。类型: 'worker' 或 'soldier'。关注点: 'stock' 或 'option'。返回纯JSON列表：[{{'name': '代号', 'type': 'soldier', 'focus': 'option', 'portfolio': ['TSLA'], 'logic': '逻辑', 'persona': '性格', 'balance': 10000, 'positions': {{}} }}]。指令：{instruction}"
            try:
                res = queen_ai.generate_content(prompt)
                clean_json = res.text.strip().replace("```json", "").replace("```", "").strip()
                new_drones = json.loads(clean_json)
                for d in new_drones:
                    supabase.table("drones").insert(d).execute()
                st.success(f"成功孵化 {len(new_drones)} 个单位！")
                st.rerun()
            except Exception as e: st.error(f"基因编码错误: {e}")

with t2:
    res = supabase.table("drones").select("*").order("type").execute()
    drones = res.data
    if not drones:
        st.info("蜂巢空虚。")
    else:
        for d in drones:
            is_soldier = d.get('type') == 'soldier'
            label = f"⚔️ {d['name']} (兵蜂)" if is_soldier else f"🔍 {d['name']} (工蜂)"
            
            with st.expander(f"{label} | 关注: {d['focus']}"):
                c1, c2, c3 = st.columns([1, 1, 1])
                if is_soldier:
                    c1.metric("资产余额", f"${d.get('balance', 0):,.2f}")
                    c2.write(f"**当前持仓:** {d.get('positions', {})}")
                else:
                    c1.write(f"**监控组合:** {d['portfolio']}")
                    c2.write(f"**目标建议:** 待巡检")
                
                c3.write(f"**核心逻辑:** {d['logic']}")
                
                # --- 删除/执行按钮 ---
                bc1, bc2 = st.columns(2)
                if bc1.button(f"🗑️ 退役 {d['name']}", key=f"del_{d['id']}"):
                    supabase.table("drones").delete().eq("id", d["id"]).execute()
                    st.toast(f"单位 {d['name']} 已从系统移除")
                    st.rerun()
                
                if d.get("logs"):
                    st.table(pd.DataFrame(d["logs"]).tail(3))

with t3:
    st.subheader("核心协议控制")
    if st.button("⚠️ 清空蜂巢 (危险操作)", type="primary"):
        supabase.table("drones").delete().neq("id", -1).execute()
        st.success("所有单位已进入回收炉。")
        st.rerun()