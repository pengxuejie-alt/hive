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
    st.error(f"连接失败: {e}"); st.stop()

def get_metrics(d):
    """计算核心指标：防御性对齐生命周期"""
    # 确保创建时间有效
    created_at_str = d.get('created_at', datetime.now(timezone.utc).isoformat())
    start = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
    age = max((datetime.now(timezone.utc) - start).total_seconds() / 3600, 0.01)
    
    # 资产处理，防止除以零
    initial = d.get('initial_balance') if d.get('initial_balance') and d.get('initial_balance') > 0 else 10000
    current = d.get('balance') if d.get('balance') is not None else initial
    
    # 计算 ROI
    roi = ((current - initial) / initial * 100)
    roi_hr = roi / age
    
    # 计算最大回撤 (MDD)
    peak = d.get('peak_balance') if d.get('peak_balance') and d.get('peak_balance') > 0 else initial
    mdd = max(0, (peak - current) / peak * 100)
    
    # Fitness 评分 (ROI_hr 与回撤的结合)
    fitness = roi_hr / (mdd + 1)
    return age, roi, roi_hr, mdd, fitness

st.title("🐝 Hive 蜂巢智能交易生态")

t1, t2, t3 = st.tabs(["👑 基因孵化", "🏆 演化排行榜", "⚙️ 系统维护"])

with t1:
    col1, col2 = st.columns([2, 1])
    with col1:
        instruction = st.text_area("蜂后指令:", placeholder="例如：孵化3只兵蜂，自主寻找当前高波动的芯片股，采用激进策略。")
    with col2:
        st.info("💡 **系统准则：**\n- 存活 < 4h：预热观察期，不进入正式排名。\n- 记忆积累：每只蜂都会从决策中学习并记录。")
    
    if st.button("开始孵化", type="primary"):
        with st.spinner("蜂后正在编码基因..."):
            prompt = f"""你是蜂后。设计单位。如果是兵蜂(soldier)，根据指令自主选择portfolio标的。
            返回纯JSON列表：[{{'name':'代号','type':'soldier','focus':'stock','portfolio':['代码'],'logic':'逻辑','persona':'性格','balance':10000,'initial_balance':10000,'memory':'初始经验。'}}]。
            指令：{instruction}"""
            try:
                res = queen_ai.generate_content(prompt)
                clean_json = res.text.strip().replace("```json", "").replace("```", "").strip()
                new_drones = json.loads(clean_json)
                for d in new_drones:
                    supabase.table("drones").insert(d).execute()
                st.success("新蜂入巢，开始4小时预热期。")
                st.rerun()
            except Exception as e: st.error(f"基因编码错误: {e}")

with t2:
    res = supabase.table("drones").select("*").execute()
    if not res.data:
        st.info("蜂巢空虚，请先孵化。")
    else:
        all_drones = []
        for d in res.data:
            age, roi, roi_hr, mdd, fitness = get_metrics(d)
            d.update({'age': age, 'roi': roi, 'roi_hr': roi_hr, 'mdd': mdd, 'fitness': fitness})
            all_drones.append(d)
        
        # 赛场分层：成熟期 (>= 4h) vs 孵化期 (< 4h)
        leaderboard = sorted([d for d in all_drones if d['age'] >= 4], key=lambda x: x['fitness'], reverse=True)
        nursery = [d for d in all_drones if d['age'] < 4]

        st.subheader("🏁 正式赛场 (已对齐每小时收益率)")
        if not leaderboard: st.write("暂无进入成熟期的单位。")
        for idx, d in enumerate(leaderboard):
            rank = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else "🐝"
            with st.expander(f"{rank} {d['name']} | Fitness: {d['fitness']:.4f} | 存活: {d['age']:.1f}h"):
                c1, c2, c3 = st.columns(3)
                c1.metric("累计ROI", f"{d['roi']:.2f}%")
                c2.metric("每小时ROI", f"{d['roi_hr']:.3f}%")
                c3.write(f"**持仓:** {d['positions']}")
                st.write(f"**🧠 经验记忆:** {d.get('memory', '尚无记录')}")
                if st.button(f"🗑️ 淘汰 {d['name']}", key=f"del_{d['id']}"):
                    supabase.table("drones").delete().eq("id", d["id"]).execute()
                    st.rerun()

        st.divider()
        st.subheader("🍼 孵化观察室 (预热中)")
        if nursery:
            for d in nursery:
                st.caption(f"**{d['name']}** - 预热进度: {d['age']:.1f}h / 4.0h")
                st.progress(min(d['age']/4.0, 1.0))

with t3:
    if st.button("🔥 触发大灭绝 (清空数据)"):
        supabase.table("drones").delete().neq("id", -1).execute()
        st.rerun()