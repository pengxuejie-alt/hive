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
    """计算核心指标：对齐生命周期，引入4小时观察期"""
    start = datetime.fromisoformat(d['created_at'].replace('Z', '+00:00'))
    age = max((datetime.now(timezone.utc) - start).total_seconds() / 3600, 0.01)
    
    # 盈亏与回撤
    initial = d.get('initial_balance', 10000)
    current = d.get('balance', 10000)
    roi = ((current - initial) / initial * 100)
    roi_hr = roi / age
    
    # 计算回撤 (MDD)
    peak = d.get('peak_balance', initial)
    mdd = max(0, (peak - current) / peak * 100)
    
    # Fitness = 风险调整后收益 (Calmar变体)
    fitness = roi_hr / (mdd + 1)
    return age, roi, roi_hr, mdd, fitness

st.title("🐝 Hive 蜂巢：智能交易与演化赛场")

t1, t2, t3 = st.tabs(["👑 基因孵化", "🏆 演化榜单", "⚙️ 系统维护"])

with t1:
    col1, col2 = st.columns([2, 1])
    with col1:
        instruction = st.text_area("蜂后指令:", placeholder="例如：孵化2只兵蜂。自主根据市场热度挑选科技标的，要求激进。")
    with col2:
        st.info("💡 **规则：**\n- 存活 < 4h：预热观察期，不入榜。\n- 存活 > 4h：进入正式赛场排名。")
    
    if st.button("注入基因并孵化", type="primary"):
        with st.spinner("蜂后正在编码..."):
            prompt = f"""
            你是蜂后。设计单位。若是兵蜂(soldier)，请根据指令自选标的。
            返回纯JSON列表：
            [{{
              "name": "代号", "type": "soldier", "focus": "stock",
              "portfolio": ["代码"], "logic": "逻辑描述", "persona": "性格基因",
              "balance": 10000, "initial_balance": 10000, "memory": "初始经验: 等待机会。"
            }}]
            指令：{instruction}
            """
            try:
                res = queen_ai.generate_content(prompt)
                new_drones = json.loads(res.text.strip().replace("```json", "").replace("```", ""))
                for d in new_drones:
                    supabase.table("drones").insert(d).execute()
                st.success("新蜂已孵化，进入观察室。")
                st.rerun()
            except Exception as e: st.error(f"失败: {e}")

with t2:
    res = supabase.table("drones").select("*").execute()
    if not res.data:
        st.info("蜂巢空虚。")
    else:
        drones_with_data = []
        for d in res.data:
            age, roi, roi_hr, mdd, fitness = get_metrics(d)
            d.update({'age': age, 'roi': roi, 'roi_hr': roi_hr, 'mdd': mdd, 'fitness': fitness})
            drones_with_data.append(d)
        
        # 分组：赛场 (>4h) vs 观察室 (<4h)
        leaderboard = sorted([d for d in drones_with_data if d['age'] >= 4], key=lambda x: x['fitness'], reverse=True)
        nursery = [d for d in drones_with_data if d['age'] < 4]

        st.subheader("🏁 正式赛场 (已对齐周期)")
        if not leaderboard: st.write("暂无成熟单位。")
        for idx, d in enumerate(leaderboard):
            rank = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else "🐝"
            with st.expander(f"{rank} {d['name']} | Fitness: {d['fitness']:.4f} | 存活: {d['age']:.1f}h"):
                c1, c2, c3 = st.columns(3)
                c1.metric("累计盈亏", f"{d['roi']:.2f}%")
                c2.metric("最大回撤", f"{d['mdd']:.2f}%")
                c3.write(f"**持仓:** {d['positions']}")
                st.write(f"**🧠 经验积累:** {d.get('memory', '尚无记录')}")
                if st.button(f"🗑️ 淘汰 {d['name']}", key=d['id']):
                    supabase.table("drones").delete().eq("id", d["id"]).execute()
                    st.rerun()

        st.divider()
        st.subheader("🍼 孵化观察室 (预热中)")
        if nursery:
            for d in nursery:
                st.caption(f"**{d['name']}** - 已观察 {d['age']:.1f}h / 4.0h")
                st.progress(min(d['age']/4.0, 1.0))

with t3:
    if st.button("🔥 清空整个生态系统"):
        supabase.table("drones").delete().neq("id", -1).execute()
        st.rerun()