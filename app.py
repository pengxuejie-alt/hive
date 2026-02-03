import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json
import requests
from datetime import datetime, timezone, timedelta
import pytz

# --- 核心配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
st.set_page_config(page_title="Hive | 蜂巢演化实验室", layout="wide", page_icon="🐝")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel(AI_MODEL_NAME)
except Exception as e:
    st.error(f"连接失败: {e}"); st.stop()

# --- 新增：远程触发 GitHub Action ---
def trigger_worker():
    headers = {
        "Authorization": f"token {st.secrets['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github.v3+json",
    }
    repo = st.secrets['GITHUB_REPO']
    url = f"https://api.github.com/repos/{repo}/actions/workflows/hive_cycle.yml/dispatches"
    data = {"ref": "main"}
    try:
        res = requests.post(url, headers=headers, json=data)
        return res.status_code == 204
    except: return False

def get_market_active_hours(created_at_str):
    et_tz = pytz.timezone('US/Eastern')
    if not created_at_str: return 0.1
    start_dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00')).astimezone(et_tz)
    now_et = datetime.now(et_tz)
    active_hours = 0.0
    curr = start_dt
    while curr < now_et:
        if curr.weekday() < 5:
            open_time = curr.replace(hour=9, minute=30, second=0)
            close_time = curr.replace(hour=16, minute=0, second=0)
            if open_time <= curr <= close_time: active_hours += 1.0
        curr += timedelta(hours=1)
    return max(active_hours, 0.1)

def get_metrics(d):
    active_age = get_market_active_hours(d.get('created_at'))
    initial = float(d.get('initial_balance') or 10000.0)
    current = float(d.get('balance') or initial)
    peak = float(d.get('peak_balance') or initial)
    roi = ((current - initial) / initial * 100) if initial > 0 else 0.0
    roi_hr = roi / active_age
    try: mdd = max(0.0, (peak - current) / peak * 100) if peak > 0 else 0.0
    except: mdd = 0.0
    mdd_penalty = (mdd * 0.5 + 1) if d.get('focus') == 'option' else (mdd + 1)
    fitness = roi_hr / mdd_penalty
    return active_age, roi, roi_hr, mdd, fitness

st.title("🐝 Hive 蜂巢：专业策略演化实验室")

# 侧边栏控制
with st.sidebar:
    st.header("🚀 调度中心")
    if st.button("🔔 立即一次性放飞所有蜜蜂"):
        if trigger_worker(): st.success("指令已下达，Worker 启动中...")
        else: st.error("触发失败，请检查 Secrets 配置。")

t1, t2, t3, t4 = st.tabs(["👑 蜂后赋能", "🏆 演化排行榜", "🧬 杂交实验室", "⚙️ 系统维护"])

with t1:
    col1, col2 = st.columns([2, 1])
    with col1:
        instruction = st.text_area("蜂后指令:", placeholder="例如：孵化3只盯GLD的中立兵蜂。")
    with col2:
        st.info("💡 **蜂后增强**：会自动分配 Iron Condor / Straddle 等机构策略基因。")
    
    if st.button("开始专业孵化", type="primary"):
        with st.spinner("蜂后正在检索策略库..."):
            prompt = f"""你是蜂后。设计兵蜂单位。
            请根据用户指令，从以下专业策略库中分配基因：
            - 中立：Iron Condor, Delta Neutral, Butterfly.
            - 激进：Long Gamma, Directional Vertical Spread.
            - 保守：Covered Call, Credit Spread.
            每只蜂必须具备独特的 logic。
            返回纯JSON列表：[{{'name':'代号','type':'soldier','focus':'option','portfolio':['标的代码'],'logic':'专业策略基因','persona':'性格基因','balance':10000,'initial_balance':10000,'memory':'初始经验：等待开盘。'}}]
            指令：{instruction}"""
            try:
                res = queen_ai.generate_content(prompt)
                new_drones = json.loads(res.text.strip().replace("```json", "").replace("```", "").strip())
                for d in new_drones:
                    d['peak_balance'] = d.get('balance', 10000.0)
                    supabase.table("drones").insert(d).execute()
                st.success("专业基因注入成功，兵蜂已入巢。")
                st.rerun()
            except Exception as e: st.error(f"失败: {e}")

with t2:
    res = supabase.table("drones").select("*").execute()
    if res.data:
        all_d = []
        for d in res.data:
            age, roi, roi_hr, mdd, fitness = get_metrics(d)
            d.update({'age_active': age, 'roi': roi, 'roi_hr': roi_hr, 'mdd': mdd, 'fitness': fitness})
            all_d.append(d)
        mature = sorted([d for d in all_d if d['age_active'] >= 4], key=lambda x: x['fitness'], reverse=True)
        nursery = sorted([d for d in all_d if d['age_active'] < 4], key=lambda x: x['age_active'], reverse=True)
        
        st.subheader("🏁 正式赛场 (>4h 盘中)")
        for idx, d in enumerate(mature):
            rank = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else "🐝"
            with st.expander(f"{rank} {d['name']} | Fitness: {d['fitness']:.4f} | 策略: {d['persona']}"):
                c1, c2, c3 = st.columns(3)
                c1.metric("累计ROI", f"{d['roi']:.2f}%")
                c2.metric("当前现金", f"${d['balance']:,.0f}")
                c3.write(f"**基因逻辑:** {d['logic']}")
                st.info(f"**🧠 后天记忆:** {d.get('memory')}")
                if st.button(f"🗑️ 淘汰 {d['name']}", key=f"del_{d['id']}"):
                    supabase.table("drones").delete().eq("id", d["id"]).execute()
                    st.rerun()

        st.divider()
        st.subheader("🍼 孵化观察室")
        for d in nursery:
            with st.expander(f"🐣 {d['name']} | 预热: {d['age_active']:.1f}h / 4h"):
                st.progress(min(d['age_active']/4.0, 1.0))
                st.write(f"策略方向: {d['persona']}")

with t3:
    st.subheader("🧬 基因杂交实验室")
    STABLE_THRESHOLD = 32.5 # 1周盘中时间
    elites = [d for d in all_d if d['age_active'] >= STABLE_THRESHOLD and d['fitness'] > 0]
    if len(elites) < 2:
        st.warning(f"目前跨周精英不足 ({STABLE_THRESHOLD}h)。")
    else:
        st.success(f"发现 {len(elites)} 只优良种蜂。")
        col1, col2 = st.columns(2)
        p1 = col1.selectbox("母本 A (Logic供体)", elites, format_func=lambda x: x['name'])
        p2 = col2.selectbox("母本 B (Persona供体)", elites, format_func=lambda x: x['name'])
        if st.button("🧬 执行基因融合", type="primary"):
            with st.spinner("正在提取遗传密码..."):
                cross_prompt = f"""你是蜂后。执行杂交。
                提取 A 的 Logic: {p1['logic']} 和 B 的 Persona: {p2['persona']}。
                注意：不要继承它们的 memory，只需生成全新的、融合后的 logic。
                返回JSON：{{'name':'{p1['name']}+','type':'soldier','focus':'option','portfolio':{p1['portfolio']},'logic':'融合基因','persona':'融合性格','balance':10000,'initial_balance':10000,'memory':'初始经验：白纸一张。'}}"""
                try:
                    res = queen_ai.generate_content(cross_prompt)
                    child = json.loads(res.text.strip().replace("```json", "").replace("```", "").strip())
                    supabase.table("drones").insert(child).execute()
                    st.success("二代兵蜂已诞生，继承了双亲的基因优点！")
                except Exception as e: st.error(f"杂交失败: {e}")

with t4:
    if st.button("🔥 触发大灭绝"):
        supabase.table("drones").delete().neq("id", -1).execute()
        st.rerun()