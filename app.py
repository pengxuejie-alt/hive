import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# --- 1. 全局配置 ---
VERSION = "v11.0 (DNA Encoding & Memory Feedback)"
st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

# --- 2. 核心辅助 ---
def parse_option_symbol(symbol):
    if not symbol.startswith("O:"): return symbol
    match = re.match(r"O:([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d+)", symbol)
    if match:
        tk, yy, mm, dd, cp, strike = match.groups()
        strike_val = int(strike) / 1000
        type_str = "Call" if cp == "C" else "Put"
        return f"{tk} {mm}/{dd} ${strike_val} {type_str}"
    return symbol

@st.cache_resource
def init_hive_engine():
    try:
        return {
            "supabase": create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]),
            "gen_client": genai.Client(api_key=st.secrets["GEMINI_KEY"]),
            "poly": RESTClient(api_key=st.secrets["POLYGON_KEY"])
        }, None
    except Exception as e: return None, str(e)

# --- 3. 🚨 核心：带记忆反馈的放飞引擎 ---
def execute_flight_v11(d, slot, clients):
    with slot:
        dna_chain = d.get('style', 'Risk:Neutral | Time:Mid')
        history = d.get('logs', [])[:3] # 取最近三条记忆
        targets = d.get('portfolio') or ['GLD']
        
        st.write(f"🚀 **{d['name']} 正在提取 DNA 经验并扫描市场...**")
        
        # 情报抓取逻辑 (保持 Aggs 穿透)
        # ... (此处省略行情抓取 fetch_tiger_intel 的重复代码，保持 v10.4 逻辑) ...
        ai_brief = {} # 假设已抓取到行情数据
        
        # 💡 记忆注入 Prompt
        memory_context = "\n".join([f"- 历史记录: {m}" for m in history]) if history else "无历史记忆。"
        
        raw_t = """
        你是工蜂 [N]。
        🧬 你的结构化 DNA 特征：[DNA]
        🧠 你的长期记忆（请根据历史盈亏调整心态）：
        [MEMORY]
        
        当前现金: $[B] | 持仓: [P] | 情报: [I]
        
        要求：
        1. 必须分析历史记忆对你当前决策的影响。
        2. 严格返回 JSON: {"thought": "基于 DNA 和记忆的分析", "trades": []}
        """
        final_prompt = raw_t.replace("[N]", d['name']).replace("[DNA]", dna_chain)\
                             .replace("[MEMORY]", memory_context).replace("[B]", f"{d['balance']:,.2f}")\
                             .replace("[P]", json.dumps(d.get('positions'))).replace("[I]", json.dumps(ai_brief))
        
        try:
            r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=final_prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            
            # 结算与日志更新...
            # 记录此时的资产水位作为下一次的记忆
            thought_with_memory = f"【进化研判】{decision.get('thought')}"
            # ... 执行数据库 update ...
            st.success(f"💭 {d['name']} 完成了具备记忆的进化研判。")
        except: st.error("研判中断")

# --- 4. UI 渲染 ---
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg
try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

tabs = st.tabs(["🏆 蜂群看板", "👑 DNA 孵化器", "⚙️ 管理"])

with tabs[1]:
    st.subheader("👑 基因特征编码孵化")
    user_cmd = st.text_input("输入孵化指令（如：孵化激进的末日博弈者）:")
    if st.button("🔥 编码 DNA 并孵化"):
        with st.spinner("🧬 正在将指令编码为结构化特征片段..."):
            dna_prompt = f"请将指令 '{user_cmd}' 转化为一段结构化的 DNA 特征链。格式要求：特征名:特征值 | 特征名:特征值。例如 Risk:Aggressive | Model:Gamma_Scalp | Mood:Greedy | Horizon:Intraday。仅返回字符串。"
            dna_res = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=dna_prompt)
            dna_chain = dna_res.text.strip()
            
            clients['supabase'].table("drones").insert({
                "name": f"AI-{random.randint(100,999)}", "style": dna_chain,
                "balance": 100000.0, "total_assets": 100000.0, "portfolio": ["GLD"], "positions": {}
            }).execute(); st.rerun()

with tabs[0]:
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | DNA: {d.get('style','-')}", expanded=True):
            # 资产看板展示逻辑 (同 v10.7)
            st.write("**🧬 DNA 特征片段:**")
            dna_fragments = d.get('style', '').split(' | ')
            cols = st.columns(len(dna_fragments) if dna_fragments else 1)
            for i, frag in enumerate(dna_fragments):
                cols[i].code(frag)
            
            # 记忆展示...