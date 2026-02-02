import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json
from datetime import datetime, timezone

# --- 核心配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
st.set_page_config(page_title="Hive | 蜂巢进化系统", layout="wide", page_icon="🐝")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel(AI_MODEL_NAME)
except Exception as e:
    st.error(f"连接云端失败: {e}"); st.stop()

def calculate_fitness(d):
    """
    计算进化表现分：
    1. 对齐时间：ROI/hr
    2. 考虑回撤：此处简化为 (当前余额 - 初始余额) / 存活时长
    """
    created_at = datetime.fromisoformat(d['created_at'].replace('Z', '+00:00'))
    hours_alive = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
    hours_alive = max(hours_alive, 0.1) 
    
    net_profit_pct = (d['balance'] - d['initial_balance']) / d['initial_balance'] * 100 if d['initial_balance'] > 0 else 0
    roi_hr = net_profit_pct / hours_alive
    
    return round(hours_alive, 1), round(net_profit_pct, 2), round(roi_hr, 4)

st.title("🐝 Hive 蜂巢：自动化交易与智能进化生态")

t1, t2, t3 = st.tabs(["👑 蜂后孵化", "📦 演化赛场", "⚙️ 进化算法"])

with t1:
    col1, col2 = st.columns([2, 1])
    with col1:
        instruction = st.text_area("蜂后指令:", placeholder="例如：孵化3个兵蜂。你要自己寻找最近表现好的3只半导体股票作为标的，采用趋势追踪策略。")
    with col2:
        st.info("💡 **孵化逻辑**：你可以指定标的，也可以让蜂后根据你的行业指令自行选择。")
    
    if st.button("注入基因并孵化", type="primary"):
        with st.spinner("蜂后正在分析市场并编码..."):
            prompt = f"""
            你是蜂后。设计单位。
            返回纯JSON列表：
            [{{
              "name": "代号",
              "type": "soldier",
              "focus": "stock",
              "portfolio": ["代码"],
              "logic": "详细的交易逻辑",
              "persona": "性格特征",
              "balance": 10000,
              "initial_balance": 10000,
              "positions": {{}}
            }}]
            指令：{instruction}
            """
            try:
                res = queen_ai.generate_content(prompt)
                clean_json = res.text.strip().replace("```json", "").replace("```", "").strip()
                new_drones = json.loads(clean_json)
                for d in new_drones:
                    supabase.table("drones").insert(d).execute()
                st.success(f"成功孵化 {len(new_drones)} 个单位！")
                st.rerun()
            except Exception as e: st.error(f"失败: {e}")

with t2:
    res = supabase.table("drones").select("*").execute()
    drones = res.data
    if not drones:
        st.info("赛场暂无单位。")
    else:
        # 计算指标并排序
        data_list = []
        for d in drones:
            hrs, roi, roi_hr = calculate_fitness(d)
            d['hrs_alive'] = hrs
            d['roi_hr'] = roi_hr
            data_list.append(d)
        
        # 按照 ROI/hr 排序（优胜劣汰的第一步）
        sorted_drones = sorted(data_list, key=lambda x: x['roi_hr'], reverse=True)
        
        for idx, d in enumerate(sorted_drones):
            is_soldier = d['type'] == 'soldier'
            rank_icon = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else "🐝"
            status = "🛡️ 观察期" if d['hrs_alive'] < 12 else "⚔️ 竞争期"
            
            with st.expander(f"{rank_icon} {d['name']} | ROI/hr: {d['roi_hr']}% | 存活: {d['hrs_alive']}h"):
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("当前现金", f"${d['balance']:,.0f}")
                col_b.write(f"**关注标的:** {d['portfolio']}")
                col_c.write(f"**状态:** {status}")
                
                st.write(f"**交易逻辑:** {d['logic']}")
                if d.get('positions'): st.code(f"持仓: {d['positions']}")
                
                if st.button(f"🗑️ 淘汰 {d['name']}", key=f"del_{d['id']}"):
                    supabase.table("drones").delete().eq("id", d["id"]).execute()
                    st.rerun()

with t3:
    st.subheader("进化参数设置")
    st.write("当前默认：观察期 = 12小时。淘汰规则 = ROI/hr 排名后 30% 且 ROI < 0。")
    if st.button("🔥 立即执行大灭绝演化"):
        st.warning("将触发一次强制筛选...")
        # 此处可以调用 worker.py 中的 natural_selection 函数逻辑