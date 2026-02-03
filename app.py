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

# --- 远程放飞逻辑 ---
def trigger_worker():
    try:
        token = st.secrets["GITHUB_TOKEN"]
        repo = st.secrets["GITHUB_REPO"]
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        # 这里的URL必须对应你仓库里的yml文件名
        url = f"https://api.github.com/repos/{repo}/actions/workflows/hive_cycle.yml/dispatches"
        res = requests.post(url, headers=headers, json={"ref": "main"})
        return res.status_code == 204
    except: return False

def get_et_time():
    return datetime.now(pytz.timezone('US/Eastern'))

def check_market_status():
    et_now = get_et_time()
    if et_now.weekday() >= 5: return "休市 (周末)", "🔴"
    open_t = et_now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = et_now.replace(hour=16, minute=0, second=0, microsecond=0)
    if et_now < open_t: return "盘前 (Pre-market)", "🟡"
    elif et_now > close_t: return "盘后 (After-hours)", "🟠"
    else: return "盘中 (Live)", "🟢"

def get_market_active_hours(created_at_str):
    et_tz = pytz.timezone('US/Eastern')
    if not created_at_str: return 0.1
    start_dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00')).astimezone(et_tz)
    now_et = datetime.now(et_tz)
    active_hours = 0.0
    curr = start_dt
    while curr < now_et:
        if curr.weekday() < 5:
            ot, ct = curr.replace(hour=9, minute=30, second=0), curr.replace(hour=16, minute=0, second=0)
            if ot <= curr <= ct: active_hours += 0.5 # 对应30min调度
        curr += timedelta(minutes=30)
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
    return active_age, roi, roi_hr, mdd, roi_hr / mdd_penalty

st.title("🐝 Hive 蜂巢：专业策略演化实验室")

with st.sidebar:
    st.header("🕒 市场时钟 (美东)")
    m_status, m_icon = check_market_status()
    st.subheader(f"{m_icon} {m_status}")
    st.write(f"当前时间: {get_et_time().strftime('%H:%M:%S')}")
    st.divider()
    if st.button("🚀 立即手动放飞所有蜜蜂"):
        if trigger_worker(): st.success("已起飞！")
        else: st.error("起飞失败，请检查 Token 效期及 yml 文件名。")

tabs = st.tabs(["👑 蜂后赋能", "🏆 演化排行榜", "🧬 杂交实验室", "⚙️ 系统维护"])

with tabs[0]:
    instruction = st.text_area("蜂后指令 (例如：孵化3只盯NVDA的中立兵蜂):")
    if st.button("执行专业孵化", type="primary"):
        with st.spinner("蜂后注入基因中..."):
            prompt = f"""你是蜂后。设计兵蜂基因。
            根据指令分配专业策略逻辑（如：Iron Condor, Delta Neutral, Vertical Spread）。
            返回纯JSON列表：[{{'name':'代号','focus':'option','portfolio':['代码'],'logic':'详细交易逻辑基因','persona':'策略名性格','balance':10000,'initial_balance':10000,'memory':'等待开盘。'}}]
            指令：{instruction}"""
            try:
                res = queen_ai.generate_content(prompt)
                new_d = json.loads(res.text.strip().replace("```json", "").replace("```", "").strip())
                for d in new_d:
                    d['peak_balance'] = d.get('balance', 10000.0)
                    supabase.table("drones").insert(d).execute()
                st.success("精英基因注入成功。"); st.rerun()
            except Exception as e: st.error(f"失败: {e}")

with tabs[1]:
    res = supabase.table("drones").select("*").execute()
    if res.data:
        all_d = []
        for d in res.data:
            age, roi, roi_hr, mdd, fitness = get_metrics(d)
            d.update({'age_active': age, 'roi': roi, 'roi_hr': roi_hr, 'mdd': mdd, 'fitness': fitness})
            all_d.append(d)
        mature = sorted([d for d in all_d if d['age_active'] >= 4], key=lambda x: x['fitness'], reverse=True)
        nursery = sorted([d for d in all_d if d['age_active'] < 4], key=lambda x: x['age_active'], reverse=True)

        def draw_drone(d, icon):
            with st.expander(f"{icon} {d['name']} | 收益: {d['roi']:.2f}% | 活跃: {d['age_active']:.1f}h"):
                c1, c2, c3 = st.columns(3)
                c1.metric("余额", f"${d['balance']:,.0f}")
                c2.write(f"**策略:** {d['persona']}")
                c3.write(f"**关注:** {d['portfolio']}")
                st.info(f"**🧠 思考过程与复盘:**\n{d.get('memory', '尚无记录')}")
                if d.get('logs'): st.json(d['logs'])
                if st.button(f"🗑️ 淘汰 {d['name']}", key=d['id']):
                    supabase.table("drones").delete().eq("id", d["id"]).execute(); st.rerun()

        st.subheader("🏁 正式赛场")
        for idx, d in enumerate(mature): draw_drone(d, "🥇" if idx==0 else "🥈" if idx==1 else "🥉" if idx==2 else "🐝")
        st.divider(); st.subheader("🍼 观察室")
        for d in nursery: draw_drone(d, "🐣"); st.progress(min(d['age_active']/4.0, 1.0))

with tabs[2]:
    st.subheader("🧬 遗传学杂交 (跨周精英)")
    STABLE = 32.5 # 1周盘中时长
    elites = [d for d in all_d if d['age_active'] >= STABLE and d['fitness'] > 0]
    if len(elites) < 2: st.warning(f"杂交门槛：需存活满盘中一周 ({STABLE}h)。")
    else:
        col1, col2 = st.columns(2)
        p1 = col1.selectbox("母本 A (Logic供体)", elites, format_func=lambda x: x['name'])
        p2 = col2.selectbox("母本 B (Persona供体)", elites, format_func=lambda x: x['name'])
        if st.button("🧬 执行基因杂交", type="primary"):
            with st.spinner("正在提取遗传密码..."):
                # 关键：只提取基因 (Logic/Persona)，丢弃后天记忆 (Memory)
                prompt = f"杂交：融合 A 的逻辑 {p1['logic']} 和 B 的性格 {p2['persona']}。生成二代纯净基因，不带任何 memory 经验。返回JSON。"
                try:
                    res = queen_ai.generate_content(prompt)
                    child = json.loads(res.text.strip().replace("```json", "").replace("```", "").strip())
                    supabase.table("drones").insert(child).execute(); st.success("二代精英诞诞生！")
                except Exception as e: st.error(f"失败: {e}")

with tabs[3]:
    if st.button("🔥 触发大灭绝"):
        supabase.table("drones").delete().neq("id", -1).execute(); st.rerun()