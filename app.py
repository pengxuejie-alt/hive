import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json

# --- 核心配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
st.set_page_config(page_title="Hive | 蜂巢数据库版", layout="wide", page_icon="🐝")

# 初始化 Supabase (从 Streamlit Secrets 读取)
try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel(AI_MODEL_NAME)
except Exception as e:
    st.error(f"连接云端失败: {e}"); st.stop()

st.title("🐝 Hive 蜂巢智能生态 (Supabase 驱动)")

t1, t2, t3 = st.tabs(["👑 蜂后孵化", "📦 实时监控", "⚙️ 系统维护"])

with t1:
    instruction = st.text_area("蜂后指令:", placeholder="例如：孵化2只工蜂，盯着半导体板块。")
    if st.button("执行演化", type="primary"):
        with st.spinner(f"蜂后 ({AI_MODEL_NAME}) 正在下达旨意..."):
            prompt = f"你是蜂后。根据指令设计工蜂，返回纯JSON列表：[{{\"name\":\"代号\",\"portfolio\":[\"代码\"],\"logic\":\"逻辑\",\"target\":70}}]。指令：{instruction}"
            try:
                res = queen_ai.generate_content(prompt)
                clean_json = res.text.strip().replace("```json", "").replace("```", "").strip()
                new_drones = json.loads(clean_json)
                for d in new_drones:
                    # 写入 Supabase 数据库
                    supabase.table("drones").insert(d).execute()
                st.success(f"成功孵化 {len(new_drones)} 只工蜂并存入云端！")
                st.rerun()
            except Exception as e: st.error(f"基因编码错误: {e}")

with t2:
    # 直接从 Supabase 读取
    res = supabase.table("drones").select("*").execute()
    drones = res.data
    if not drones:
        st.info("蜂巢目前是空的，请先孵化工蜂。")
    else:
        for d in drones:
            with st.expander(f"🐝 {d['name']} | 状态: {d.get('status','ACTIVE')}"):
                st.write(f"**巡检组合:** {d['portfolio']}")
                st.write(f"**核心逻辑:** {d['logic']}")
                if d.get("logs"):
                    st.table(pd.DataFrame(d["logs"]).tail(5))

with t3:
    if st.button("🧨 格式化数据库"):
        # 删除所有数据（危险操作）
        supabase.table("drones").delete().neq("id", -1).execute()
        st.rerun()