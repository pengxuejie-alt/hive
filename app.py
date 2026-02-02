import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json
from datetime import datetime, timezone

# --- 核心配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
st.set_page_config(page_title="Hive | 虎之眼进化系统", layout="wide", page_icon="🐝")

# 初始化客户端
try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel(AI_MODEL_NAME)
except Exception as e:
    st.error(f"连接云端失败: {e}"); st.stop()

def calculate_metrics(d):
    """
    公平对齐算法：
    计算 ROI/hr (每小时收益率)，确保不同时间孵化的蜂可以公平竞争
    """
    # 转换时间，确保时区一致
    created_at = datetime.fromisoformat(d['created_at'].replace('Z', '+00:00'))
    now = datetime.now(timezone.utc)
    duration_hrs = (now - created_at).total_seconds() / 3600
    duration_hrs = max(duration_hrs, 0.1) # 防止除零
    
    # 盈亏计算
    initial = d.get('initial_balance', 1)
    current = d.get('balance', 0)
    # 这里只算了现金，建议未来在 worker.py 加入持仓估值后统一更新 balance
    net_profit = current - initial
    roi_total = (net_profit / initial) * 100
    roi_per_hour = roi_total / duration_hrs
    
    return round(duration_hrs, 1), round(roi_total, 2), round(roi_per_hour, 4)

st.title("🐝 Hive 蜂巢：自动化进化生态 (虎之眼)")

t1, t2, t3 = st.tabs(["👑 蜂后孵化 (Evolution)", "📦 赛场监控 (Arena)", "⚙️ 系统维护 (System)"])

with t1:
    col1, col2 = st.columns([2, 1])
    with col1:
        instruction = st.text_area("蜂后指令:", placeholder="例如：孵化3个兵蜂，1个专注NVDA正股，2个专注TSLA期权，都要激进型。")
    with col2:
        st.info("""
        **进化准则：**
        - **工蜂 (Worker)**：只看不做，负责情报。
        - **兵蜂 (Soldier)**：实盘模拟，执行交易。
        - **对齐**：通过 ROI/hr 排名，末位者将被系统自动淘汰。
        """)
    
    if st.button("开始基因编码", type="primary"):
        with st.spinner("蜂后正在注入原始基因..."):
            prompt = f"""
            你是蜂后。根据指令设计生物单位。
            类型: 'worker'(工蜂) 或 'soldier'(兵蜂)
            关注点: 'stock'(正股) 或 'option'(期权)
            返回纯JSON列表格式，严禁包含其他文字：
            [{{
              "name": "代号",
              "type": "soldier",
              "focus": "option",
              "portfolio": ["TSLA"],
              "logic": "交易策略描述",
              "persona": "性格基因(如:极度贪婪, 严控回撤等)",
              "balance": 10000,
              "initial_balance": 10000,
              "positions": {{}}
            }}]
            指令内容：{instruction}
            """
            try:
                res = queen_ai.generate_content(prompt)
                clean_json = res.text.strip().replace("```json", "").replace("```", "").strip()
                new_drones = json.loads(clean_json)
                for d in new_drones:
                    supabase.table("drones").insert(d).execute()
                st.success(f"成功孵化 {len(new_drones)} 个新单位！")
                st.rerun()
            except Exception as e:
                st.error(f"孵化失败: {e}\nAI返回内容: {res.text}")

with t2:
    # 获取所有单位并按 ROI/hr 排序
    res = supabase.table("drones").select("*").execute()
    drones = res.data
    
    if not drones:
        st.info("赛场目前空虚。")
    else:
        # 预计算指标并排序
        processed_drones = []
        for d in drones:
            hrs, roi_total, roi_hr = calculate_metrics(d)
            d['hrs_alive'] = hrs
            d['roi_total'] = roi_total
            d['roi_hr'] = roi_hr
            processed_drones.append(d)
        
        # 按照每小时收益率降序排列
        processed_drones.sort(key=lambda x: x['roi_hr'], reverse=True)

        st.subheader("🏆 演化赛场排行榜 (按 ROI/hr 排序)")
        
        for idx, d in enumerate(processed_drones):
            # 视觉反馈：前三名和待淘汰者
            rank_icon = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else "🐝"
            is_soldier = d['type'] == 'soldier'
            
            # 状态标记
            status_text = "🛡️ 保护期" if d['hrs_alive'] < 12 else "⚔️ 竞争中"
            risk_color = "red" if (d['hrs_alive'] >= 12 and d['roi_hr'] < 0) else "green"
            
            with st.expander(f"{rank_icon} {d['name']} | ROI/hr: :{risk_color}[{d['roi_hr']}%] | 存活: {d['hrs_alive']}h"):
                c1, c2, c3, c4 = st.columns(4)
                
                c1.metric("累计ROI", f"{d['roi_total']}%")
                if is_soldier:
                    c2.metric("当前现金", f"${d['balance']:,.0f}")
                else:
                    c2.write("**类型:** 侦察工蜂")
                
                c3.write(f"**关注:** {d['portfolio']}")
                c4.write(f"**状态:** {status_text}")

                st.divider()
                st.write(f"**性格基因:** {d.get('persona', '无')}")
                st.write(f"**底层逻辑:** {d.get('logic', '无')}")
                
                if d.get('positions'):
                    st.json(d['positions'])
                
                # 底部按钮
                bc1, bc2 = st.columns([1, 4])
                if bc1.button(f"🗑️ 淘汰", key=f"del_{d['id']}"):
                    supabase.table("drones").delete().eq("id", d["id"]).execute()
                    st.rerun()
                
                if d.get("logs"):
                    st.caption("最近运行日志")
                    st.table(pd.DataFrame(d["logs"]).tail(3))

with t3:
    st.header("系统底层控制")
    col_a, col_b = st.columns(2)
    with col_a:
        st.warning("清理操作不可逆，请谨慎。")
        if st.button("🔥 触发大灭绝 (清空所有单位)"):
            supabase.table("drones").delete().neq("id", -1).execute()
            st.success("环境已初始化。")
            st.rerun()
    with col_b:
        st.info("如需修改淘汰规则（如观察时长），请修改 worker.py 中的 natural_selection 函数。")