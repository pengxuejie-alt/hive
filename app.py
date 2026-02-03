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

# --- 远程触发 GitHub Action ---
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

# --- 时间与市场状态逻辑 ---
def get_et_time():
    return datetime.now(pytz.timezone('US/Eastern'))

def check_market_status():
    et_now = get_et_time()
    if et_now.weekday() >= 5:
        return "休市 (周末)", "🔴"
    
    open_time = et_now.replace(hour=9, minute=30, second=0)
    close_time = et_now.replace(hour=16, minute=0, second=0)
    
    if et_now < open_time:
        return "盘前 (Pre-market)", "🟡"
    elif et_now > close_time:
        return "盘后 (After-hours)", "🟠"
    else:
        return "盘中 (Live)", "🟢"

def get_market_active_hours(created_at_str):
    et_tz = pytz.timezone('US/Eastern')
    if not created_at_str: return 0.1
    start_dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00')).astimezone(et_tz)
    now_et = datetime.now(et_tz)
    active_hours = 0.0
    curr = start_dt
    while curr < now_et:
        if curr.weekday() < 5:
            open_t = curr.replace(hour=9, minute=30, second=0)
            close_t = curr.replace(hour=16, minute=0, second=0)
            if open_t <= curr <= close_t: active_hours += 1.0
        curr += timedelta(hours=1)
    return max(active_hours, 0.1)

def get_metrics(d):
    active_age, initial = get_market_active_hours(d.get('created_at')), float(d.get('initial_balance') or 10000.0)
    current = float(d.get('balance') or initial)
    peak = float(d.get('peak_balance') or initial)
    roi = ((current - initial) / initial * 100) if initial > 0 else 0.0
    roi_hr = roi / active_age
    try: mdd = max(0.0, (peak - current) / peak * 100) if peak > 0 else 0.0
    except: mdd = 0.0
    mdd_penalty = (mdd * 0.5 + 1) if d.get('focus') == 'option' else (mdd + 1)
    return active_age, roi, roi_hr, mdd, roi_hr / mdd_penalty

# --- 侧边栏：状态显示 ---
st.title("🐝 Hive 蜂巢：专业策略演化实验室")

with st.sidebar:
    st.header("🕒 市场时钟 (美东)")
    m_status, m_icon = check_market_status()
    st.subheader(f"{m_icon} {m_status}")
    st.write(f"当前时间: {get_et_time().strftime('%H:%M:%S')}")
    st.divider()
    st.header("🚀 调度控制")
    if st.button("🔔 立即手动放飞所有蜜蜂"):
        if trigger_worker(): st.success("指令已发出！")
        else: st.error("请检查 Secrets 配置。")

# --- Tabs 逻辑 (渲染细节) ---
t1, t2, t3, t4 = st.tabs(["👑 蜂后赋能", "🏆 演化排行榜", "🧬 杂交实验室", "⚙️ 系统维护"])

with t1:
    instruction = st.text_area("蜂后指令 (例如：孵化3只盯NVDA的中立兵蜂):")
    if st.button("开始孵化", type="primary"):
        with st.spinner("蜂后注入基因中..."):
            prompt = f"""你是蜂后。分配专业策略基因（如Iron Condor, Vertical Spread）。
            返回JSON列表：[{{'name':'代号','type':'soldier','focus':'option','portfolio':['代码'],'logic':'专业策略逻辑','persona':'性格与策略名','balance':10000,'initial_balance':10000,'memory':'等待开盘'}}]
            指令：{instruction}"""
            try:
                res = queen_ai.generate_content(prompt)
                for d in json.loads(res.text.strip().replace("```json", "").replace("```", "").strip()):
                    d['peak_balance'] = d.get('balance', 10000.0)
                    supabase.table("drones").insert(d).execute()
                st.success("孵化成功。"); st.rerun()
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

        def show_drone(d, icon):
            with st.expander(f"{icon} {d['name']} | 收益: {d['roi']:.2f}% | 活跃: {d['age_active']:.1f}h"):
                c1, c2, c3 = st.columns(3)
                c1.metric("现金", f"${d['balance']:,.0f}")
                c2.write(f"**策略基因:** {d['persona']}")
                c3.write(f"**关注:** {d['portfolio']}")
                st.info(f"**🧠 思考与复盘:** {d.get('memory', '学习中...')}")
                if d.get('logs'): st.json(d['logs'])
                if st.button(f"🗑️ 淘汰 {d['name']}", key=d['id']):
                    supabase.table("drones").delete().eq("id", d["id"]).execute()
                    st.rerun()

        st.subheader("🏁 正式赛场")
        for idx, d in enumerate(mature):
            show_drone(d, "🥇" if idx==0 else "🥈" if idx==1 else "🥉" if idx==2 else "🐝")
        st.divider()
        st.subheader("🍼 观察室")
        for d in nursery:
            show_drone(d, "🐣")
            st.progress(min(d['age_active']/4.0, 1.0))

with t3:
    st.subheader("🧬 杂交实验室")
    STABLE = 32.5 # 1周活跃时长
    elites = [d for d in all_d if d['age_active'] >= STABLE and d['fitness'] > 0]
    if len(elites) < 2:
        st.warning(f"目前还没有存活满一周盘中时间（{STABLE}h）的精英。")
    else:
        col1, col2 = st.columns(2)
        p1 = col1.selectbox("母本 A (Logic)", elites, format_func=lambda x: x['name'])
        p2 = col2.selectbox("母本 B (Persona)", elites, format_func=lambda x: x['name'])
        if st.button("🧬 执行基因融合", type="primary"):
            with st.spinner("融合中..."):
                cross_prompt = f"杂交单位。提取 A 的 Logic: {p1['logic']} 和 B 的 Persona: {p2['persona']}。忽略后天memory，生成全新基因。返回纯JSON。"
                try:
                    res = queen_ai.generate_content(cross_prompt)
                    child = json.loads(res.text.strip().replace("```json", "").replace("```", "").strip())
                    supabase.table("drones").insert(child).execute()
                    st.success("二代精英诞生！")
                except Exception as e: st.error(f"失败: {e}")

with t4:
    if st.button("🔥 触发大灭绝"):
        supabase.table("drones").delete().neq("id", -1).execute(); st.rerun()