import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json
from datetime import datetime, timezone

# --- 配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
st.set_page_config(page_title="Hive | 蜂巢演化实验室", layout="wide", page_icon="🐝")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel(AI_MODEL_NAME)
except Exception as e:
    st.error(f"连接失败: {e}"); st.stop()

def get_metrics(d):
    """计算核心指标，防御性处理除零"""
    created_at_str = d.get('created_at', datetime.now(timezone.utc).isoformat())
    start = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
    age = max((datetime.now(timezone.utc) - start).total_seconds() / 3600, 0.01)
    
    initial = d.get('initial_balance') if d.get('initial_balance', 0) > 0 else 10000
    current = d.get('balance') if d.get('balance') is not None else initial
    
    roi = ((current - initial) / initial * 100)
    roi_hr = roi / age
    
    # 记录最高点以计算回撤
    peak = d.get('peak_balance') if d.get('peak_balance', 0) > 0 else initial
    mdd = max(0, (peak - current) / peak * 100)
    
    # Fitness 评分：对于期权(高波动)，我们适当降低回撤对分数的打压
    mdd_factor = (mdd * 0.5 + 1) if d.get('focus') == 'option' else (mdd + 1)
    fitness = roi_hr / mdd_factor
    return age, roi, roi_hr, mdd, fitness

st.title("🐝 Hive 蜂巢：长周期演化实验室")

t1, t2, t3, t4 = st.tabs(["👑 基因孵化", "🏆 演化排行榜", "🧬 杂交实验室", "⚙️ 系统维护"])

with t1:
    col1, col2 = st.columns([2, 1])
    with col1:
        instruction = st.text_area("蜂后指令:", placeholder="例如：孵化3个兵蜂，关注虎之眼金融项目，专注期权。")
    with col2:
        st.info("💡 **系统逻辑：**\n- 存活满 168h (1周) 方可进入杂交实验室。\n- 观察期 4h 以前不入榜。")
    
    if st.button("开始孵化", type="primary"):
        with st.spinner("蜂后正在注入原始基因..."):
            prompt = f"你是蜂后。设计单位。若是兵蜂(soldier)，根据指令自选portfolio。返回纯JSON列表：[{{'name':'代号','type':'soldier','focus':'option','portfolio':['代码'],'logic':'逻辑','persona':'性格','balance':10000,'initial_balance':10000,'memory':'初始经验'}}]。指令：{instruction}"
            try:
                res = queen_ai.generate_content(prompt)
                new_drones = json.loads(res.text.strip().replace("```json", "").replace("```", "").strip())
                for d in new_drones:
                    supabase.table("drones").insert(d).execute()
                st.success("新蜂入场。")
                st.rerun()
            except Exception as e: st.error(f"失败: {e}")

with t2:
    res = supabase.table("drones").select("*").execute()
    if res.data:
        d_list = []
        for d in res.data:
            age, roi, roi_hr, mdd, fitness = get_metrics(d)
            d.update({'age': age, 'roi': roi, 'roi_hr': roi_hr, 'mdd': mdd, 'fitness': fitness})
            d_list.append(d)
        
        mature = sorted([d for d in d_list if d['age'] >= 4], key=lambda x: x['fitness'], reverse=True)
        nursery = [d for d in d_list if d['age'] < 4]

        st.subheader("🏁 正式赛场 (存活 >= 4h)")
        for idx, d in enumerate(mature):
            rank = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else "🐝"
            with st.expander(f"{rank} {d['name']} | Fitness: {d['fitness']:.4f} | ROI/hr: {d['roi_hr']:.2f}%"):
                c1, c2, c3 = st.columns(3)
                c1.metric("累计ROI", f"{d['roi']:.2f}%")
                c2.metric("当前余额", f"${d['balance']:,.0f}")
                c3.write(f"**关注:** {d['portfolio']}")
                st.info(f"**🧠 经验积累:** {d.get('memory', '尚无记录')}")
                if st.button(f"🗑️ 淘汰 {d['name']}", key=f"del_{d['id']}"):
                    supabase.table("drones").delete().eq("id", d["id"]).execute()
                    st.rerun()

        st.divider()
        st.subheader("🍼 孵化观察室 (< 4h)")
        for d in nursery:
            st.caption(f"🐣 {d['name']} | 性格: {d['persona']} | 预热: {d['age']:.1f}h/4h")
            st.progress(min(d['age']/4.0, 1.0))

with t3:
    st.subheader("🧬 优胜者杂交 (Crossover)")
    STABLE_THRESHOLD = 168 # 一周
    elites = [d for d in d_list if d['age'] >= STABLE_THRESHOLD and d['fitness'] > 0]
    
    if len(elites) < 2:
        st.warning(f"目前符合‘一周赛场’筛选条件的优胜者不足（需存活 > {STABLE_THRESHOLD}h）。")
    else:
        st.success(f"发现 {len(elites)} 只经受住一周考验的精英！")
        col_a, col_b = st.columns(2)
        p1 = col_a.selectbox("精英 A", elites, format_func=lambda x: f"{x['name']} (ROI: {x['roi']}%)")
        p2 = col_b.selectbox("精英 B", elites, format_func=lambda x: f"{x['name']} (ROI: {x['roi']}%)")
        
        if st.button("🧬 执行跨代杂交", type="primary"):
            with st.spinner("蜂后正在融合基因..."):
                cross_prompt = f"分析两个存活了一周的优胜兵蜂。A: {p1['logic']}, {p1['memory']}。B: {p2['logic']}, {p2['memory']}。融合两者的逻辑和经验，孵化V2.0。返回纯JSON。"
                try:
                    res = queen_ai.generate_content(cross_prompt)
                    child = json.loads(res.text.strip().replace("```json", "").replace("```", "").strip())
                    supabase.table("drones").insert(child).execute()
                    st.success(f"精英后代 {child['name']} 已入场！")
                except Exception as e: st.error(f"失败: {e}")

with t4:
    if st.button("🔥 触发大灭绝"):
        supabase.table("drones").delete().neq("id", -1).execute()
        st.rerun()