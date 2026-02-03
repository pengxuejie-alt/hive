import streamlit as st
import pandas as pd
from supabase import create_client
import google.generativeai as genai
import json
import requests
from datetime import datetime, timezone, timedelta
import pytz
from polygon import RESTClient

# --- 核心配置 ---
AI_MODEL_NAME = "gemini-3-flash-preview"
st.set_page_config(page_title="Hive | 虎之眼演化实验室", layout="wide", page_icon="🐝")

# 初始化客户端
try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    queen_ai = genai.GenerativeModel(AI_MODEL_NAME)
    poly_client = RESTClient(api_key=st.secrets["POLYGON_KEY"])
except Exception as e:
    st.error(f"核心服务连接失败，请检查 Secrets 配置: {e}")
    st.stop()

# --- 辅助函数 ---
def trigger_worker():
    try:
        token = st.secrets["GITHUB_TOKEN"].strip()
        repo = st.secrets["GITHUB_REPO"].strip()
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        url = f"https://api.github.com/repos/{repo}/actions/workflows/hive_cycle.yml/dispatches"
        res = requests.post(url, headers=headers, json={"ref": "main"})
        return res.status_code == 204
    except: return False

def get_live_asset_value(positions):
    total_mkt_val = 0.0
    details = []
    if not positions: return 0.0, []
    for symbol, qty in positions.items():
        try:
            if symbol.startswith("O:"):
                px = poly_client.get_last_trade(symbol).price
                mv = float(qty) * float(px) * 100 
            else:
                px = poly_client.get_snapshot_ticker("stocks", symbol).last_trade.p
                mv = float(qty) * float(px)
            total_mkt_val += mv
            details.append({"标的": symbol, "数量": qty, "现价": f"${px:.2f}", "市值": f"${mv:.2f}"})
        except:
            details.append({"标的": symbol, "数量": qty, "现价": "数据获取中", "市值": "0.0"})
    return total_mkt_val, details

# --- 侧边栏 ---
with st.sidebar:
    st.header("🕒 虎之眼控制中心")
    et_now = datetime.now(pytz.timezone('US/Eastern'))
    st.write(f"美东时间: {et_now.strftime('%H:%M:%S')}")
    if st.button("🚀 立即放飞巡检"):
        if trigger_worker(): st.success("已触发 GitHub Actions")
        else: st.error("触发失败")
    st.divider()

# --- 定义三个标签页 ---
# 确保这里定义了 3 个，且顺序固定
tabs = st.tabs(["🏆 蜂群实战列表", "👑 蜂后孵化", "⚙️ 系统维护"])

# --- Tab 1: 实战列表 ---
with tabs[0]:
    try:
        res = supabase.table("drones").select("*").execute()
        if not res.data:
            st.info("目前蜂巢没有兵蜂，请前往‘蜂后孵化’。")
        else:
            for d in res.data:
                # 资产计算
                cash = float(d.get('balance') or 10000.0)
                mkt_val, pos_details = get_live_asset_value(d.get('positions', {}))
                total_assets = cash + mkt_val
                
                with st.expander(f"🐝 {d['name']} | 总资产: ${total_assets:,.2f}"):
                    c1, c2 = st.columns(2)
                    c1.metric("现金", f"${cash:,.0f}")
                    c2.metric("持仓市值", f"${mkt_val:,.2f}")
                    if pos_details: st.table(pd.DataFrame(pos_details))
                    st.info(f"**🧠 经验:** {d.get('memory', '暂无记录')}")
                    
                    # 独立修复按钮
                    sc1, sc2 = st.columns(2)
                    if sc1.button("🩹 修复账本", key=f"fix_{d['id']}"):
                        supabase.table("drones").update({"balance":10000.0, "positions":{}, "peak_balance":10000.0}).eq("id", d["id"]).execute()
                        st.rerun()
                    if sc2.button("🗑️ 淘汰", key=f"del_{d['id']}"):
                        supabase.table("drones").delete().eq("id", d["id"]).execute()
                        st.rerun()
    except Exception as e:
        st.error(f"排行榜渲染出错: {e}")

# --- Tab 2: 蜂后孵化 ---
with tabs[1]:
    st.subheader("👑 基因工程：孵化新兵蜂")
    instruction = st.text_area("输入孵化指令:", height=150, placeholder="例如：孵化2只针对 NVDA 的激进期权策略兵蜂")
    if st.button("开始基因注入", type="primary"):
        with st.spinner("蜂后正在编码..."):
            try:
                prompt = f"设计兵蜂。返回纯JSON列表：[{{'name':'代号','focus':'option','portfolio':['代码'],'logic':'逻辑','persona':'性格','balance':10000,'initial_balance':10000,'memory':'等待开盘'}}]。指令：{instruction}"
                res = queen_ai.generate_content(prompt)
                new_drones = json.loads(res.text.strip().replace("```json", "").replace("```", "").strip())
                for d in new_drones:
                    d['peak_balance'] = 10000.0
                    supabase.table("drones").insert(d).execute()
                st.success("孵化完成！")
                st.rerun()
            except Exception as e:
                st.error(f"孵化失败: {e}")

# --- Tab 3: 系统维护 ---
with tabs[2]:
    st.header("⚙️ 深度维护")
    if st.button("🩹 一键修复全体账本 (保留记忆)", type="primary"):
        supabase.table("drones").update({"balance": 10000.0, "positions": {}, "peak_balance": 10000.0}).neq("id", -1).execute()
        st.success("已修复！")
        st.rerun()
    
    st.divider()
    if st.button("🔥 全体大灭绝"):
        if st.checkbox("确认清空所有数据？"):
            supabase.table("drones").delete().neq("id", -1).execute()
            st.rerun()