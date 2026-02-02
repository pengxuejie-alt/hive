import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json
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

def get_market_active_hours(created_at_str):
    """计算从创建至今的‘美股盘中有效小时数’ (ET 09:30-16:00, 剔除周末)"""
    et_tz = pytz.timezone('US/Eastern')
    if not created_at_str:
        return 0.1
    # 处理 Supabase 返回的时间字符串
    start_dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00')).astimezone(et_tz)
    now_et = datetime.now(et_tz)
    
    active_hours = 0.0
    curr = start_dt
    while curr < now_et:
        if curr.weekday() < 5:  # 周一到周五
            open_time = curr.replace(hour=9, minute=30, second=0)
            close_time = curr.replace(hour=16, minute=0, second=0)
            if open_time <= curr <= close_time:
                active_hours += 1.0
        curr += timedelta(hours=1)
    return max(active_hours, 0.1)

def get_metrics(d):
    """核心进化指标计算：彻底修复 NoneType 错误"""
    # 1. 活跃时间计算
    active_age = get_market_active_hours(d.get('created_at'))
    
    # 2. 资产防御处理：强制转换为 float 并设置默认值防止 None 导致的 TypeError
    initial = float(d.get('initial_balance') or 10000.0)
    current = float(d.get('balance') or initial)
    peak = float(d.get('peak_balance') or initial)
    
    # 3. 收益计算
    roi = ((current - initial) / initial * 100) if initial > 0 else 0.0
    roi_hr = roi / active_age
    
    # 4. 最大回撤计算 (MDD)
    try:
        mdd = max(0.0, (peak - current) / peak * 100) if peak > 0 else 0.0
    except:
        mdd = 0.0
    
    # 5. Fitness 评分 (期权单位对回撤的容忍度设为更高)
    mdd_penalty = (mdd * 0.5 + 1) if d.get('focus') == 'option' else (mdd + 1)
    fitness = roi_hr / mdd_penalty
    
    return active_age, roi, roi_hr, mdd, fitness

st.title("🐝 Hive 蜂巢：盘中演化实验室")

t1, t2, t3, t4 = st.tabs(["👑 基因孵化", "🏆 演化排行榜", "🧬 杂交实验室", "⚙️ 系统维护"])

with t1:
    col1, col2 = st.columns([2, 1])
    with col1:
        instruction = st.text_area("蜂后指令:", placeholder="例如：孵化3个兵蜂，专注期权博弈。")
    if st.button("开始孵化", type="primary"):
        with st.spinner("蜂后编码中..."):
            prompt = f"你是蜂后。设计单位。若是兵蜂(soldier)，根据指令自选portfolio。返回纯JSON列表：[{{'name':'代号','type':'soldier','focus':'option','portfolio':['代码'],'logic':'逻辑','persona':'性格','balance':10000,'initial_balance':10000,'memory':'初始基因'}}]。指令：{instruction}"
            try:
                res = queen_ai.generate_content(prompt)
                new_drones = json.loads(res.text.strip().replace("```json", "").replace("```", "").strip())
                for d in new_drones:
                    # 强力初始化，防止 peak_balance 出现 None
                    d['peak_balance'] = d.get('balance', 10000.0)
                    supabase.table("drones").insert(d).execute()
                st.success("新蜂入巢。")
                st.rerun()
            except Exception as e: st.error(f"失败: {e}")

with t2:
    res = supabase.table("drones").select("*").execute()
    if res.data:
        all_drones = []
        for d in res.data:
            age, roi, roi_hr, mdd, fitness = get_metrics(d)
            d.update({'age_active': age, 'roi': roi, 'roi_hr': roi_hr, 'mdd': mdd, 'fitness': fitness})
            all_drones.append(d)
        
        # 盘中4小时预热
        mature = sorted([d for d in all_drones if d['age_active'] >= 4], key=lambda x: x['fitness'], reverse=True)
        nursery = sorted([d for d in all_drones if d['age_active'] < 4], key=lambda x: x['age_active'], reverse=True)

        st.subheader("🏁 正式赛场 (存活 >= 4 盘中小时)")
        for idx, d in enumerate(mature):
            rank = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else "🐝"
            with st.expander(f"{rank} {d['name']} | ROI/hr(盘中): {d['roi_hr']:.2f}% | 活跃: {d['age_active']:.1f}h"):
                c1, c2, c3 = st.columns(3)
                c1.metric("累计ROI", f"{d['roi']:.2f}%")
                c2.metric("当前现金", f"${d['balance']:,.0f}")
                c3.write(f"**关注:** {d['portfolio']}")
                st.info(f"**🧠 经验:** {d.get('memory', '学习中...')}")
                if st.button(f"🗑️ 淘汰 {d['name']}", key=f"del_{d['id']}"):
                    supabase.table("drones").delete().eq("id", d["id"]).execute()
                    st.rerun()

        st.divider()
        st.subheader("🍼 孵化观察室 (预热中)")
        for d in nursery:
            with st.expander(f"🐣 {d['name']} | 进度: {d['age_active']:.1f}h / 4h"):
                st.progress(min(d['age_active']/4.0, 1.0))
                st.write(f"**性格:** {d['persona']}")
                st.write(f"**余额:** ${d['balance']}")

with t3:
    st.subheader("🧬 精英杂交实验室")
    WEEK_THRESHOLD = 32.5 # 5个交易日 * 6.5小时
    elites = [d for d in all_drones if d['age_active'] >= WEEK_THRESHOLD and d['fitness'] > 0]
    if len(elites) < 2:
        st.warning(f"门槛不足：需存活满盘中一周 ({WEEK_THRESHOLD}h)。")
    else:
        st.success(f"发现 {len(elites)} 只跨周精英！")
        # 此处可以继续添加 Selectbox 进行杂交操作

with t4:
    if st.button("🔥 触发大灭绝 (格式化系统)"):
        supabase.table("drones").delete().neq("id", -1).execute()
        st.rerun()