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

# --- 远程触发 GitHub Action (修复 KeyError 并增加异常处理) ---
def trigger_worker():
    try:
        # 必须在 Streamlit Secrets 中配置 GITHUB_TOKEN 和 GITHUB_REPO
        token = st.secrets["GITHUB_TOKEN"]
        repo = st.secrets["GITHUB_REPO"]
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        # 确保 yml 文件名与仓库一致
        url = f"https://api.github.com/repos/{repo}/actions/workflows/hive_cycle.yml/dispatches"
        data = {"ref": "main"}
        res = requests.post(url, headers=headers, json=data)
        return res.status_code == 204
    except Exception as e:
        st.error(f"调度器错误: 请确保 Secrets 中已配置 GITHUB_TOKEN 和 GITHUB_REPO。具体错误: {e}")
        return False

# --- 市场状态与时钟逻辑 ---
def get_et_time():
    return datetime.now(pytz.timezone('US/Eastern'))

def check_market_status():
    et_now = get_et_time()
    if et_now.weekday() >= 5:
        return "休市 (周末)", "🔴"
    
    open_time = et_now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_time = et_now.replace(hour=16, minute=0, second=0, microsecond=0)
    
    if et_now < open_time:
        return "盘前 (Pre-market)", "🟡"
    elif et_now > close_time:
        return "盘后 (After-hours)", "🟠"
    else:
        return "盘中 (Live)", "🟢"

def get_market_active_hours(created_at_str):
    """计算美股盘中有效小时数"""
    et_tz = pytz.timezone('US/Eastern')
    if not created_at_str: return 0.1
    start_dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00')).astimezone(et_tz)
    now_et = datetime.now(et_tz)
    active_hours = 0.0
    curr = start_dt
    while curr < now_et:
        if curr.weekday() < 5:
            ot = curr.replace(hour=9, minute=30, second=0)
            ct = curr.replace(hour=16, minute=0, second=0)
            if ot <= curr <= ct: active_hours += 0.5 # 对应30min调度
        curr += timedelta(minutes=30)
    return max(active_hours, 0.1)

def get_metrics(d):
    """核心演化指标"""
    age_active = get_market_active_hours(d.get('created_at'))
    initial = float(d.get('initial_balance') or 10000.0)
    current = float(d.get('balance') or initial)
    peak = float(d.get('peak_balance') or initial)
    
    roi = ((current - initial) / initial * 100) if initial > 0 else 0.0
    roi_hr = roi / age_active
    
    try: mdd = max(0.0, (peak - current) / peak * 100) if peak > 0 else 0.0
    except: mdd = 0.0
    
    mdd_penalty = (mdd * 0.5 + 1) if d.get('focus') == 'option' else (mdd + 1)
    fitness = roi_hr / mdd_penalty
    return age_active, roi, roi_hr, mdd, fitness

# --- 侧边栏 ---
st.title("🐝 Hive 蜂巢：专业策略演化实验室")

with st.sidebar:
    st.header("🕒 市场时钟 (美东)")
    m_status, m_icon = check_market_status()
    st.subheader(f"{m_icon} {m_status}")
    st.write(f"当前时间: {get_et_time().strftime('%H:%M:%S')}")
    st.divider()
    st.header("🚀 调度控制")
    if st.button("🔔 立即一次性放飞所有蜜蜂"):
        if trigger_worker():
            st.success("指令已发出！Worker 正在启动...")
        else:
            st.error("启动失败，请检查 Secrets 配置。")

t1, t2, t3, t4 = st.tabs(["👑 蜂后赋能", "🏆 演化排行榜", "🧬 杂交实验室", "⚙️ 系统维护"])

with t1:
    col1, col2 = st.columns([2, 1])
    with col1:
        instruction = st.text_area("蜂后指令:", placeholder="例如：孵化3只盯NVDA的中立兵蜂。")
    with col2:
        st.info("💡 **蜂后增强**：会自动分配 Iron Condor / Vertical Spread 等专业机构策略基因。")
    
    if st.button("开始专业孵化", type="primary"):
        with st.spinner("蜂后正在分析全球金融策略库..."):
            enhanced_prompt = f"""
            你是蜂后。设计兵蜂单位。
            请根据用户指令，从以下专业策略库中分配基因：
            - 中立：Iron Condor, Delta Neutral, Butterfly Spread.
            - 激进：Long Gamma, Directional Vertical Spread, Straddle.
            - 保守：Covered Call, Cash-Secured Put, Credit Spread.
            每只蜂必须具备独特的 logic，并在 persona 中体现其策略特质。
            返回纯JSON列表：[{{'name':'代号','type':'soldier','focus':'option','portfolio':['代码'],'logic':'详细交易逻辑','persona':'策略名及性格','balance':10000,'initial_balance':10000,'memory':'初始经验'}}]
            指令：{instruction}
            """
            try:
                res = queen_ai.generate_content(enhanced_prompt)
                new_drones = json.loads(res.text.strip().replace("```json", "").replace("```", "").strip())
                for d in new_drones:
                    d['peak_balance'] = d.get('balance', 10000.0)
                    supabase.table("drones").insert(d).execute()
                st.success("专业兵蜂已就位。"); st.rerun()
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

        def render_drone(d, icon):
            with st.expander(f"{icon} {d['name']} | 收益: {d['roi']:.2f}% | 盘中活跃: {d['age_active']:.1f}h"):
                c1, c2, c3 = st.columns(3)
                c1.metric("余额", f"${d['balance']:,.0f}")
                c2.metric("ROI/hr", f"{d['roi_hr']:.2f}%")
                c3.write(f"**策略形态:** {d['persona']}")
                
                st.write("**🧬 基因逻辑:**")
                st.caption(d['logic'])
                
                st.write("**🧠 思考过程与最新复盘:**")
                st.info(d.get('memory', '尚无记忆记录'))
                
                if d.get('logs'):
                    st.write("**📜 交易明细:**")
                    st.json(d['logs'])
                
                if st.button(f"🗑️ 淘汰 {d['name']}", key=f"del_{d['id']}"):
                    supabase.table("drones").delete().eq("id", d["id"]).execute()
                    st.rerun()

        st.subheader("🏁 正式赛场 (>4h 盘中)")
        for idx, d in enumerate(mature):
            render_drone(d, "🥇" if idx==0 else "🥈" if idx==1 else "🥉" if idx==2 else "🐝")
        st.divider()
        st.subheader("🍼 孵化观察室")
        for d in nursery:
            render_drone(d, "🐣")
            st.progress(min(d['age_active']/4.0, 1.0))

with t3:
    st.subheader("🧬 精英基因杂交")
    STABLE = 32.5 # 一周盘中时长
    elites = [d for d in all_d if d['age_active'] >= STABLE and d['fitness'] > 0]
    if len(elites) < 2:
        st.warning(f"目前跨周精英不足 ({STABLE}h)。")
    else:
        st.success(f"发现 {len(elites)} 只优良种蜂。")
        col1, col2 = st.columns(2)
        p1 = col1.selectbox("母本 A (Logic)", elites, format_func=lambda x: x['name'])
        p2 = col2.selectbox("母本 B (Persona)", elites, format_func=lambda x: x['name'])
        if st.button("🧬 执行基因杂交", type="primary"):
            with st.spinner("正在提取遗传密码..."):
                cross_prompt = f"杂交。提取 A 的 Logic: {p1['logic']} 和 B 的 Persona: {p2['persona']}。忽略后天记忆，生成全新基因。返回纯JSON。"
                try:
                    res = queen_ai.generate_content(cross_prompt)
                    child = json.loads(res.text.strip().replace("```json", "").replace("```", "").strip())
                    supabase.table("drones").insert(child).execute()
                    st.success("二代精英已诞生。")
                except Exception as e: st.error(f"失败: {e}")

with t4:
    if st.button("🔥 触发大灭绝"):
        supabase.table("drones").delete().neq("id", -1).execute(); st.rerun()