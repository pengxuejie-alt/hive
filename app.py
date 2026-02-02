import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json
from datetime import datetime, timezone

# --- 核心配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
st.set_page_config(page_title="Hive | 蜂巢实验室", layout="wide", page_icon="🐝")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel(AI_MODEL_NAME)
except Exception as e:
    st.error(f"连接失败: {e}"); st.stop()

def get_metrics(d):
    """计算核心指标，增加防御性编程"""
    created_at_str = d.get('created_at', datetime.now(timezone.utc).isoformat())
    start = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
    age = max((datetime.now(timezone.utc) - start).total_seconds() / 3600, 0.01)
    
    initial = d.get('initial_balance') if d.get('initial_balance') and d.get('initial_balance') > 0 else 10000
    current = d.get('balance') if d.get('balance') is not None else initial
    
    roi = ((current - initial) / initial * 100)
    roi_hr = roi / age
    peak = d.get('peak_balance') if d.get('peak_balance') and d.get('peak_balance') > 0 else initial
    mdd = max(0, (peak - current) / peak * 100)
    fitness = roi_hr / (mdd + 1)
    return age, roi, roi_hr, mdd, fitness

st.title("🐝 Hive 蜂巢：自动化交易与智能进化生态")

t1, t2, t3 = st.tabs(["👑 基因孵化", "🏆 演化排行榜", "⚙️ 系统维护"])

with t1:
    col1, col2 = st.columns([2, 1])
    with col1:
        instruction = st.text_area("蜂后指令:", placeholder="例如：孵化3个兵蜂，自主寻找芯片股。")
    if st.button("开始孵化", type="primary"):
        with st.spinner("蜂后编码中..."):
            prompt = f"你是蜂后。设计单位。若是兵蜂(soldier)，根据指令自选portfolio。返回纯JSON列表：[{{'name':'代号','type':'soldier','focus':'stock','portfolio':['代码'],'logic':'逻辑','persona':'性格','balance':10000,'initial_balance':10000,'memory':'初始经验。'}}]。指令：{instruction}"
            try:
                res = queen_ai.generate_content(prompt)
                new_drones = json.loads(res.text.strip().replace("```json", "").replace("```", "").strip())
                for d in new_drones:
                    supabase.table("drones").insert(d).execute()
                st.success("新蜂入巢，开始4小时预热观察期。")
                st.rerun()
            except Exception as e: st.error(f"孵化失败: {e}")

with t2:
    res = supabase.table("drones").select("*").execute()
    if not res.data:
        st.info("蜂巢空虚。")
    else:
        d_list = []
        for d in res.data:
            age, roi, roi_hr, mdd, fitness = get_metrics(d)
            d.update({'age': age, 'roi': roi, 'roi_hr': roi_hr, 'mdd': mdd, 'fitness': fitness})
            d_list.append(d)
        
        leaderboard = sorted([d for d in d_list if d['age'] >= 4], key=lambda x: x['fitness'], reverse=True)
        nursery = sorted([d for d in d_list if d['age'] < 4], key=lambda x: x['age'], reverse=True)

        # --- 正式赛场展示 ---
        st.subheader("🏁 正式赛场 (存活 >= 4h)")
        for idx, d in enumerate(leaderboard):
            rank = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else "🐝"
            with st.expander(f"{rank} {d['name']} | Fitness: {d['fitness']:.4f} | ROI/hr: {d['roi_hr']:.2f}%"):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("累计盈亏", f"{d['roi']:.2f}%")
                c2.metric("当前现金", f"${d['balance']:,.0f}")
                c3.write(f"**关注:** {d['portfolio']}")
                c4.write(f"**存活:** {d['age']:.1f}h")
                st.info(f"**🧠 经验记忆:** {d.get('memory', '尚无记录')}")
                st.caption(f"**交易性格:** {d.get('persona')}")
                if d.get("logs"): st.table(pd.DataFrame(d["logs"]).tail(3))
                if st.button(f"🗑️ 淘汰 {d['name']}", key=f"del_{d['id']}"):
                    supabase.table("drones").delete().eq("id", d["id"]).execute()
                    st.rerun()

        st.divider()

        # --- 观察室展示 (现在能看到所有细节) ---
        st.subheader("🍼 孵化观察室 (预热期细节监控)")
        if not nursery:
            st.write("目前没有正在预热的单位。")
        else:
            for d in nursery:
                with st.expander(f"🐣 {d['name']} | 预热进度: {d['age']:.1f}h / 4.0h | 盈亏: {d['roi']}%"):
                    # 进度条
                    st.progress(min(d['age']/4.0, 1.0))
                    
                    c1, c2, c3 = st.columns(3)
                    c1.write(f"**账户余额:** ${d['balance']:,.0f}")
                    c2.write(f"**性格:** {d.get('persona', '未知')}")
                    c3.write(f"**标的:** {d['portfolio']}")
                    
                    st.write(f"**初步经验:** {d.get('memory', '学习中...')}")
                    
                    # 观察期的实时行为日志
                    if d.get("logs"):
                        st.caption("最新行为记录:")
                        st.table(pd.DataFrame(d["logs"]).tail(2))
                    
                    if st.button(f"🚫 提前终止 {d['name']}", key=f"nurs_{d['id']}"):
                        supabase.table("drones").delete().eq("id", d["id"]).execute()
                        st.rerun()

with t3:
    if st.button("🔥 触发大灭绝 (格式化)"):
        supabase.table("drones").delete().neq("id", -1).execute()
        st.rerun()