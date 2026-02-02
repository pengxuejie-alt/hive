import streamlit as st
import pandas as pd
import json
import os
import google.generativeai as genai

# --- 核心配置 ---
# 严格遵循您的意志，使用您认可的模型名称
AI_MODEL_NAME = "gemini-3-flash-preview"
HIVE_FILE = "hive.json"

st.set_page_config(page_title="Hive | 蜂巢控制系统", layout="wide", page_icon="🐝")

@st.cache_resource
def init_queen():
    # 确保初始化时使用正确的模型 ID
    return genai.GenerativeModel(AI_MODEL_NAME)

# --- 初始化 API ---
try:
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = init_queen()
except Exception as e:
    st.error(f"密钥配置异常: {e}")
    st.stop()

# --- 数据持久化 ---
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
    st.subheader("向蜂后下达演化指令")
    instruction = st.text_area(
        "蜂后指令 (Queen's Command):", 
        placeholder="例如：孵化1只工蜂侦察兵。盯着 BABA 和 FXI 的价差联动。",
        height=150
    )
    
    if st.button("执行演化", type="primary"):
        if not instruction:
            st.warning("请先输入指令。")
        else:
            with st.spinner(f"蜂后正在使用 {AI_MODEL_NAME} 编译基因..."):
                prompt = f"""
                你是蜂后。请根据指令设计工蜂，必须严格返回纯 JSON 列表格式，不要包含任何解释文字。
                格式示例：[{{"name":"代号","portfolio":["代码1"],"logic":"逻辑","target":70}}]
                指令：{instruction}
                """
                try:
                    res = queen_ai.generate_content(prompt)
                    # 强力清洗 AI 返回的 Markdown 代码块标签
                    clean_json = res.text.strip().replace("```json", "").replace("```", "").strip()
                    new_drones = json.loads(clean_json)
                    
                    for d in new_drones:
                        # 初始化工蜂的标准属性
                        d.update({
                            "honey_count": 0, 
                            "logs": [], 
                            "status": "ACTIVE", 
                            "pnl": 0.0,
                            "style": d.get("style", "技术派")
                        })
                    
                    hive["drones"].extend(new_drones)
                    save_hive(hive)
                    st.success(f"✅ 成功孵化 {len(new_drones)} 只工蜂！模型：{AI_MODEL_NAME}")
                    st.rerun()
                except Exception as e:
                    st.error(f"基因编码错误: {e}")
                    st.info("建议：检查 API Key 权限或稍后再试。")

with t2:
    if not hive["drones"]:
        st.info("蜂巢尚无工蜂。请前往“蜂后孵化”页面创建。")
    else:
        for i, d in enumerate(hive["drones"]):
            # 根据状态显示不同颜色
            status_color = "🟢" if d.get("status") == "ACTIVE" else "🔴"
            with st.expander(f"{status_color} {d['name']} | 目标: {d['target']}% | 盈亏: {d.get('pnl', 0):+.2f}%"):
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.write("**📊 巡检组合:**")
                    st.write(d['portfolio'])
                with col2:
                    st.write("**🧠 核心基因:**")
                    st.info(d['logic'])
                
                if d.get("logs"):
                    st.write("**📋 最近采蜜记录:**")
                    df_logs = pd.DataFrame(d["logs"])
                    st.dataframe(df_logs.tail(5), use_container_width=True)
                else:
                    st.caption("暂无巡检记录，等待 GitHub Actions 触发。")

with t3:
    st.subheader("蜂巢管理")
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🧨 格式化蜂巢", help="清空所有工蜂数据"):
            save_hive({"queen": "Alpha", "drones": []})
            st.rerun()
    with col_b:
        st.write(f"当前驱动模型: `{AI_MODEL_NAME}`")