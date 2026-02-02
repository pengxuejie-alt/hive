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
    col1, col2 = st.columns(2)
    with col1:
        instruction = st.text_area("蜂后指令:", placeholder="例如：孵化一个激进的兵蜂，专注NVDA期权，追求翻倍。")
    with col2:
        st.info("💡 兵蜂(Soldier)可执行交易，工蜂(Worker)仅提醒。")
    
    if st.button("执行演化", type="primary"):
        with st.spinner("蜂后正在编码基因..."):
            prompt = f"""
            你是蜂后。根据指令设计单位。
            类型: 'worker'(工蜂) 或 'soldier'(兵蜂)
            关注: 'stock'(正股) 或 'option'(期权)
            返回纯JSON列表：
            [{{
              "name": "代号",
              "type": "soldier",
              "focus": "option",
              "portfolio": ["TSLA"],
              "logic": "逻辑描述",
              "persona": "性格特征(最大回撤/利润追求)",
              "balance": 10000,
              "positions": {{}}
            }}]
            指令：{instruction}
            """
            try:
                res = queen_ai.generate_content(prompt)
                new_drones = json.loads(res.text.strip().replace("```json", "").replace("```", ""))
                for d in new_drones:
                    supabase.table("drones").insert(d).execute()
                st.success(f"成功孵化 {len(new_drones)} 个单位！")
                st.rerun()
            except Exception as e: st.error(f"孵化失败: {e}")

with t2:
    res = supabase.table("drones").select("*").execute()
    drones = res.data
    if not drones:
        st.info("蜂巢空虚。")
    else:
        for d in drones:
            icon = "⚔️" if d['type'] == 'soldier' else "🔍"
            with st.expander(f"{icon} {d['name']} [{d['type'].upper()}] - 关注: {d['focus']}"):
                c1, c2, c3 = st.columns(3)
                c1.metric("资产余额", f"${d.get('balance', 0):,.2f}")
                c2.write(f"**关注标的:** {d['portfolio']}")
                c3.write(f"**当前持仓:** {d.get('positions', {})}")
                
                st.text(f"逻辑特征: {d['persona']}")
                
                if st.button(f"手动触发 {d['name']} 执行", key=d['id']):
                    st.warning("正在调用外部 Worker 执行，请查看控制台日志。")
                
                if d.get("logs"):
                    st.table(pd.DataFrame(d["logs"]).tail(5))

with t3:
    if st.button("清空所有单位"):
        supabase.table("drones").delete().neq("id", -1).execute()
        st.rerun()