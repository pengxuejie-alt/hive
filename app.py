import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json
from datetime import datetime, timezone

# --- 配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
st.set_page_config(page_title="Hive | 蜂巢实验室", layout="wide", page_icon="🐝")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel(AI_MODEL_NAME)
except Exception as e:
    st.error(f"连接失败: {e}"); st.stop()

def get_metrics(d):
    """计算核心进化指标"""
    start = datetime.fromisoformat(d['created_at'].replace('Z', '+00:00'))
    age = max((datetime.now(timezone.utc) - start).total_seconds() / 3600, 0.01)
    
    # 收益与回撤
    roi = ((d['balance'] - d['initial_balance']) / d['initial_balance'] * 100) if d['initial_balance'] > 0 else 0
    roi_hr = roi / age
    mdd = max(0, (d.get('peak_balance', d['initial_balance']) - d['balance']) / d.get('peak_balance', 1) * 100)
    
    # Fitness = 风险调整后收益 (Calmar 变体)
    fitness = roi_hr / (mdd + 1)
    return age, roi, roi_hr, mdd, fitness

st.title("🐝 Hive 蜂巢：自动化交易与智能进化生态")

t1, t2, t3 = st.tabs(["👑 基因孵化", "🏆 演化排行榜", "⚙️ 系统维护"])

with t1:
    col1, col2 = st.columns([2, 1])
    with col1:
        instruction = st.text_area("蜂后指令:", placeholder="例如：孵化2只兵蜂，自主寻找当前高波动的科技股进行日内交易。")
    with col2:
        st.info("💡 **逻辑说明**：\n- 未满4小时的蜂不进入正式排名。\n- 满12小时且表现极差的蜂将被自动淘汰。")
    
    if st.button("注入基因并孵化", type="primary"):
        with st.spinner("蜂后正在编码..."):
            prompt = f"你是蜂后。设计单位。如果是soldier，根据指令自主选择portfolio标的。返回纯JSON列表：[{{'name':'代号','type':'soldier','focus':'stock','portfolio':['代码'],'logic':'逻辑','persona':'性格','balance':10000,'initial_balance':10000,'memory':'初始教训。'}}]。指令：{instruction}"
            try:
                res = queen_ai.generate_content(prompt)
                new_drones = json.loads(res.text.strip().replace("```json", "").replace("```", ""))
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
        all_drones = []
        for d in res.data:
            age, roi, roi_hr, mdd, fitness = get_metrics(d)
            d.update({'age': age, 'roi': roi, 'roi_hr': roi_hr, 'mdd': mdd, 'fitness': fitness})
            all_drones.append(d)
        
        # 分组：正式赛场 (>= 4h) vs 孵化室 (< 4h)
        leaderboard = [d for d in all_drones if d['age'] >= 4]
        nursery = [d for d in all_drones if d['age'] < 4]
        
        st.subheader("🏁 正式赛场 (存活 > 4h)")
        if not leaderboard:
            st.write("暂无进入成熟期的单位。")
        else:
            sorted_leader = sorted(leaderboard, key=lambda x: x['fitness'], reverse=True)
            for idx, d in enumerate(sorted_leader):
                rank = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else "🐝"
                with st.expander(f"{rank} {d['name']} | Fitness: {d['fitness']:.4f} | 盈亏: {d['roi']}%"):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("每小时收益", f"{d['roi_hr']:.3f}%")
                    c2.metric("当前现金", f"${d['balance']:,.0f}")
                    c3.write(f"**持仓:** {d['positions']}")
                    st.write(f"**🧠 经验记忆:** {d.get('memory', '尚无记录')}")
                    if st.button(f"🗑️ 手动淘汰 {d['name']}", key=f"del_{d['id']}"):
                        supabase.table("drones").delete().eq("id", d["id"]).execute()
                        st.rerun()

        st.divider()
        st.subheader("🍼 孵化观察室 (存活 < 4h)")
        if not nursery:
            st.write("目前没有新蜂。")
        else:
            cols = st.columns(len(nursery) if len(nursery) < 4 else 4)
            for i, d in enumerate(nursery):
                with cols[i % 4]:
                    st.write(f"**{d['name']}**")
                    st.caption(f"已观察: {d['age']:.1f}h")
                    st.progress(min(d['age']/4.0, 1.0))

with t3:
    if st.button("🔥 清空整个生态系统"):
        supabase.table("drones").delete().neq("id", -1).execute()
        st.rerun()