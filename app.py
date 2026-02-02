import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json
from datetime import datetime, timezone

# --- 核心配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
st.set_page_config(page_title="Hive | 虎之眼进化", layout="wide", page_icon="🐝")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel(AI_MODEL_NAME)
except Exception as e:
    st.error(f"连接失败: {e}"); st.stop()

def calculate_metrics(d):
    """计算公平对齐的表现指标"""
    start_time = datetime.fromisoformat(d['created_at'].replace('Z', '+00:00'))
    hours_alive = (datetime.now(timezone.utc) - start_time).total_seconds() / 3600
    hours_alive = max(hours_alive, 0.1) # 防止除以0
    
    # 这里的 ROI 计算基于现金。在 worker.py 中可以进一步加入持仓市值。
    net_profit = d['balance'] - d['initial_balance']
    roi_total = (net_profit / d['initial_balance'] * 100) if d['initial_balance'] > 0 else 0
    roi_per_hour = roi_total / hours_alive
    
    return hours_alive, roi_total, roi_per_hour

st.title("🐝 Hive 蜂巢：自动化进化生态 (虎之眼项目)")

t1, t2, t3 = st.tabs(["👑 基因孵化", "📦 赛场监控", "⚙️ 系统维护"])

with t1:
    col1, col2 = st.columns([2, 1])
    with col1:
        instruction = st.text_area("蜂后指令:", placeholder="例如：孵化3只兵蜂。1只稳健型投NVDA正股，2只激进型投TSLA期权。")
    with col2:
        st.info("🧬 **进化逻辑**：系统会记录出生时间，按每小时收益率(ROI/hr)进行公平排名。")
    
    if st.button("开始演化", type="primary"):
        with st.spinner("蜂后正在编码..."):
            prompt = f"你是蜂后。设计单位。类型:'worker'|'soldier'。关注:'stock'|'option'。返回JSON列表：[{{'name':'代号','type':'soldier','focus':'option','portfolio':['AAPL'],'logic':'策略','persona':'性格','balance':10000,'initial_balance':10000,'positions':{{}} }}]。指令：{instruction}"
            try:
                res = queen_ai.generate_content(prompt)
                new_drones = json.loads(res.text.strip().replace("```json", "").replace("```", ""))
                for d in new_drones:
                    supabase.table("drones").insert(d).execute()
                st.success(f"成功孵化 {len(new_drones)} 个单位！")
                st.rerun()
            except Exception as e: st.error(f"编码失败: {e}")

with t2:
    res = supabase.table("drones").select("*").execute()
    drones = res.data
    if not drones:
        st.info("赛场暂无单位。")
    else:
        # 数据转换与排序
        for d in drones:
            hrs, roi, roi_hr = calculate_metrics(d)
            d['hrs_alive'] = round(hrs, 1)
            d['roi_total'] = round(roi, 2)
            d['roi_hr'] = round(roi_hr, 4)
        
        sorted_drones = sorted(drones, key=lambda x: x['roi_hr'], reverse=True)
        
        for idx, d in enumerate(sorted_drones):
            is_soldier = d['type'] == 'soldier'
            rank = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else "🐝"
            
            with st.expander(f"{rank} {d['name']} ({d['type']}) | ROI/hr: {d['roi_hr']}% | 存活: {d['hrs_alive']}h"):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("累计利润", f"{d['roi_total']}%")
                c2.metric("当前现金", f"${d['balance']:,.0f}")
                c3.write(f"**关注:** {d['portfolio']}")
                c4.write(f"**性格:** {d['persona']}")
                
                # 持仓展示
                if d['positions']: st.code(f"当前持仓: {d['positions']}")
                
                # 单独删除
                if st.button(f"🗑️ 淘汰 {d['name']}", key=f"del_{d['id']}"):
                    supabase.table("drones").delete().eq("id", d["id"]).execute()
                    st.rerun()

with t3:
    if st.button("⚠️ 全局格式化 (灭绝计划)"):
        supabase.table("drones").delete().neq("id", -1).execute()
        st.rerun()