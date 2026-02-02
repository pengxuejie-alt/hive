import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json
from datetime import datetime, timezone, timedelta
import pytz

# --- 配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
st.set_page_config(page_title="Hive | 蜂巢演化实验室", layout="wide", page_icon="🐝")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel(AI_MODEL_NAME)
except Exception as e:
    st.error(f"连接失败: {e}"); st.stop()

def get_market_active_hours(created_at):
    """计算从创建至今的盘中有效小时数 (美东 09:30-16:00, 剔除周末)"""
    et_tz = pytz.timezone('US/Eastern')
    start_time = datetime.fromisoformat(created_at.replace('Z', '+00:00')).astimezone(et_tz)
    now = datetime.now(et_tz)
    
    active_hours = 0.0
    current = start_time
    
    # 步进计算（简单模型，按小时扫描）
    while current < now:
        # 0-4 是周一到周五
        if current.weekday() < 5:
            # 盘中时间段：09:30 - 16:00
            day_start = current.replace(hour=9, minute=30, second=0)
            day_end = current.replace(hour=16, minute=0, second=0)
            if day_start <= current <= day_end:
                active_hours += 1.0 # 假设 worker 每小时运行一次，计为1小时
        current += timedelta(hours=1)
    
    return max(active_hours, 0.1)

def get_metrics(d):
    """基于盘中时间计算指标"""
    age_active = get_market_active_hours(d['created_at'])
    initial = d.get('initial_balance', 10000)
    current = d.get('balance', 10000)
    roi = ((current - initial) / initial * 100)
    
    # ROI/hr 现在基于盘中活跃时间
    roi_hr = roi / age_active
    peak = d.get('peak_balance', initial)
    mdd = max(0, (peak - current) / peak * 100)
    
    mdd_factor = (mdd * 0.5 + 1) if d.get('focus') == 'option' else (mdd + 1)
    fitness = roi_hr / mdd_factor
    return age_active, roi, roi_hr, mdd, fitness

st.title("🐝 Hive 蜂巢：盘中演化实验室")

t1, t2, t3, t4 = st.tabs(["👑 基因孵化", "🏆 演化排行榜", "🧬 杂交实验室", "⚙️ 系统维护"])

with t1:
    instruction = st.text_area("蜂后指令:", placeholder="例如：孵化3个兵蜂，专注期权。")
    if st.button("开始孵化", type="primary"):
        with st.spinner("编码中..."):
            prompt = f"你是蜂后。设计兵蜂。返回JSON列表：[{{'name':'代号','type':'soldier','focus':'option','portfolio':['代码'],'logic':'逻辑','persona':'性格','balance':10000,'initial_balance':10000,'memory':'初始基因'}}]。指令：{instruction}"
            try:
                res = queen_ai.generate_content(prompt)
                new_drones = json.loads(res.text.strip().replace("```json", "").replace("```", "").strip())
                for d in new_drones:
                    supabase.table("drones").insert(d).execute()
                st.success("新蜂入场，预热时钟将在下个开盘日启动。")
                st.rerun()
            except Exception as e: st.error(f"失败: {e}")

with t2:
    res = supabase.table("drones").select("*").execute()
    if res.data:
        d_list = []
        for d in res.data:
            age, roi, roi_hr, mdd, fitness = get_metrics(d)
            d.update({'age_active': age, 'roi': roi, 'roi_hr': roi_hr, 'mdd': mdd, 'fitness': fitness})
            d_list.append(d)
        
        # 4小时盘中预热
        mature = sorted([d for d in d_list if d['age_active'] >= 4], key=lambda x: x['fitness'], reverse=True)
        nursery = sorted([d for d in d_list if d['age_active'] < 4], key=lambda x: x['age_active'], reverse=True)

        st.subheader("🏁 正式赛场 (存活 >= 4 盘中小时)")
        for idx, d in enumerate(mature):
            rank = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else "🐝"
            with st.expander(f"{rank} {d['name']} | ROI/hr(盘中): {d['roi_hr']:.2f}% | 活跃时长: {d['age_active']:.1f}h"):
                c1, c2, c3 = st.columns(3)
                c1.metric("累计ROI", f"{d['roi']:.2f}%")
                c2.metric("当前余额", f"${d['balance']:,.0f}")
                c3.write(f"**关注:** {d['portfolio']}")
                st.info(f"**🧠 经验积累:** {d.get('memory', '尚无记录')}")
                if st.button(f"🗑️ 淘汰 {d['name']}", key=f"del_{d['id']}"):
                    supabase.table("drones").delete().eq("id", d["id"]).execute()
                    st.rerun()

        st.divider()
        st.subheader("🍼 孵化观察室 (盘中时钟累计中)")
        for d in nursery:
            st.caption(f"🐣 {d['name']} | 预热: {d['age_active']:.1f}h / 4h (仅限开盘时间)")
            st.progress(min(d['age_active']/4.0, 1.0))

with t3:
    st.subheader("🧬 优胜者杂交")
    # 门槛：168小时活跃时间（约等于25个交易日，即一个月）
    # 如果想按“自然周”的盘中时间，大概是 6.5h * 5 = 32.5 小时
    STABLE_THRESHOLD = 32.5 
    elites = [d for d in d_list if d['age_active'] >= STABLE_THRESHOLD and d['fitness'] > 0]
    
    if len(elites) < 2:
        st.warning(f"需存活满一周盘中时间 ({STABLE_THRESHOLD}h) 才能杂交。")
    else:
        # ... (杂交逻辑同前)
        pass

with t4:
    if st.button("🔥 触发大灭绝"):
        supabase.table("drones").delete().neq("id", -1).execute()
        st.rerun()