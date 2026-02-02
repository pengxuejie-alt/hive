import streamlit as st
import pandas as pd
import json
import os
import google.generativeai as genai

# --- 核心配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
HIVE_FILE = "hive.json"

st.set_page_config(page_title="Hive | 蜂巢控制系统", layout="wide", page_icon="🐝")

@st.cache_resource
def init_queen():
    return genai.GenerativeModel(AI_MODEL_NAME)

try:
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = init_queen()
except Exception as e:
    st.error("请在 Secrets 中配置 GEMINI_KEY"); st.stop()

def get_hive():
    if os.path.exists(HIVE_FILE):
        try:
            with open(HIVE_FILE, "r", encoding='utf-8') as f:
                return json.load(f)
        except:
            return {"queen": "Alpha", "drones": []}
    return {"queen": "Alpha", "drones": []}

def save_hive(data):
    with open(HIVE_FILE, "w", encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# --- UI 渲染 ---
st.title("🐝 Hive 蜂巢智能生态")

hive = get_hive()
t1, t2, t3 = st.tabs(["👑 蜂后孵化", "📦 蜂巢监控", "⚙️ 维护"])

with t1:
    instruction = st.text_area("蜂后指令 (Queen's Command):", 
                              placeholder="例如：孵化1只工蜂。盯住 BABA 和 FXI 的联动。")
    if st.button("执行演化", type="primary"):
        with st.spinner(f"蜂后 ({AI_MODEL_NAME}) 正在编译基因..."):
            prompt = f"你是蜂后。根据指令设计工蜂，返回纯JSON列表：[{{\"name\":\"代号\",\"portfolio\":[\"代码1\"],\"logic\":\"逻辑\",\"target\":70,\"style\":\"性格\"}}]。指令：{instruction}"
            try:
                res = queen_ai.generate_content(prompt)
                clean_json = res.text.strip().replace("```json", "").replace("```", "").strip()
                new_drones = json.loads(clean_json)
                for d in new_drones:
                    d.update({"honey_count": 0, "logs": [], "status": "ACTIVE", "pnl": 0.0})
                hive["drones"].extend(new_drones)
                save_hive(hive)
                st.success(f"成功孵化 {len(new_drones)} 只工蜂！")
                st.rerun()
            except Exception as e:
                st.error(f"基因编码错误: {e}")

with t2:
    if not hive.get("drones"):
        st.info("蜂巢尚无工蜂。")
    else:
        for d in hive["drones"]:
            with st.expander(f"🐝 {d['name']} | 状态: {d.get('status','ACTIVE')} | 盈亏: {d.get('pnl',0):+.2f}%"):
                st.write(f"**巡检范围:** {', '.join(d['portfolio'])}")
                st.write(f"**核心逻辑:** {d['logic']}")
                if d.get("logs"):
                    st.table(pd.DataFrame(d["logs"]).tail(5))

with t3:
    if st.button("🧨 格式化蜂巢"):
        save_hive({"queen": "Alpha", "drones": []})
        st.rerun()