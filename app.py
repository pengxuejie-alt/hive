import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 🚨 红线 1: 全局配置与 UI 强制渲染
# ==========================================
VERSION = "v11.1 (Full Metrics & DNA Restore)"
st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")
st.caption(f"{VERSION} | 结构化 DNA 模式已激活")

# ==========================================
# 🚨 红线 2: 核心引擎初始化 (修复 NameError)
# ==========================================
@st.cache_resource
def init_hive_engine():
    try:
        # 从 Streamlit Secrets 读取 Key
        pk = st.secrets["POLYGON_KEY"]
        gk = st.secrets["GEMINI_KEY"]
        su = st.secrets["SUPABASE_URL"]
        sk = st.secrets["SUPABASE_KEY"]
        return {
            "supabase": create_client(su, sk),
            "gen_client": genai.Client(api_key=gk),
            "poly": RESTClient(api_key=pk)
        }, None
    except Exception as e:
        return None, f"引擎启动失败: {str(e)}"

# ==========================================
# 🚨 红线 3: 虎眼级取价与解析工具
# ==========================================
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

def parse_option_symbol(symbol):
    if not symbol.startswith("O:"): return symbol
    match = re.match(r"O:([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d+)", symbol)
    if match:
        tk, yy, mm, dd, cp, strike = match.groups()
        strike_val = int(strike) / 1000
        type_str = "Call" if cp == "C" else "Put"
        return f"{tk} {mm}/{dd} ${strike_val} {type_str}"
    return symbol

def calculate_age(created_at_str):
    try:
        created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
        now = datetime.now(pytz.UTC)
        delta = now - created_at
        if delta.days > 0: return f"{delta.days}天 {delta.seconds // 3600}小时"
        return f"{delta.seconds // 3600}小时"
    except: return "刚刚诞生"

def get_verified_price_v4(poly, symbol):
    """暴力穿透 Aggs 取价法，解决 404 和 0 报价问题"""
    ticker = symbol if symbol.startswith("O:") else f"O:{symbol}"
    try:
        end = datetime.now()
        start = end - timedelta(days=3)
        # 1. 尝试分钟线
        aggs = poly.get_aggs(ticker, 1, "minute", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if aggs: return float(aggs[-1].close)
        # 2. 尝试日线兜底
        daily_aggs = poly.get_aggs(ticker, 1, "day", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        return float(daily_aggs[-1].close) if daily_aggs else 0.01
    except: return 0.01

# ==========================================
# 🚀 主逻辑启动
# ==========================================
cl_pkg, err = init_hive_engine()
if err: 
    st.error(err)
    st.info("请检查 .streamlit/secrets.toml 是否配置了所有必要的 Key。")
    st.stop()
clients = cl_pkg

# 获取数据库数据
try:
    d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except Exception as e:
    st.error(f"数据库读取失败: {e}")
    d_res = []

tabs = st.tabs(["🏆 蜂群看板", "👑 DNA 孵化器", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res:
        st.info("目前没有活跃工蜂，请前往“DNA 孵化器”创建。")
    
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | 状态: 活跃", expanded=True):
            # --- 💰 资产穿透核算 ---
            cash = float(d.get('balance', 100000.0))
            pos = d.get('positions', {})
            mv_total = 0.0
            pos_table = []
            
            if pos:
                with st.status(f"🔍 正在穿透 {d['name']} 的持仓行情...", expanded=False):
                    for sym, qty in pos.items():
                        unit_px = get_verified_price_v4(clients['poly'], sym)
                        item_mv = unit_px * qty * (100 if sym.startswith("O:") else 1)
                        mv_total += item_mv
                        pos_table.append({
                            "合约": parse_option_symbol(sym),
                            "数量": f"{qty} 手",
                            "单价": f"${unit_px:.4f}",
                            "市值": f"${item_mv:,.2f}"
                        })

            total_assets = cash + mv_total
            pnl_pct = ((total_assets / 100000.0) - 1) * 100

            # --- 📊 资产看板 (回归) ---
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("现金 (Cash)", f"${cash:,.2f}")
            m2.metric("持仓市值", f"${mv_total:,.2f}")
            m3.metric("总资产", f"${total_assets:,.2f}", delta=f"{pnl_pct:.2f}%")
            m4.metric("存活年龄", calculate_age(d.get('created_at')))

            st.divider()

            # --- 🧬 DNA 展示区 (重构) ---
            st.write("🧬 **DNA 特征片段 (Genetic Fragments)**")
            dna_raw = d.get('style', 'Risk:Neutral')
            if " | " in dna_raw:
                dna_fragments = dna_raw.split(' | ')
                cols = st.columns(len(dna_fragments))
                for i, frag in enumerate(dna_fragments):
                    cols[i].code(frag)
            else:
                # 兼容旧的长句子描述
                st.info(f"原始基因描述: {dna_raw}")

            st.divider()

            # --- 🧠 记忆与持仓 ---
            c1, c2 = st.columns([1, 1.5])
            with c1:
                st.write("🧠 **长期记忆 (Long-term Memory)**")
                logs = d.get('logs') or []
                if logs:
                    with st.container(height=250):
                        for log in logs:
                            st.caption(f"🔘 {log}")
                else:
                    st.caption("暂无历史记忆...")
                
                if st.button(f"🚀 单独放飞 {d['name']}", key=f"f_{d['id']}", type="primary", use_container_width=True):
                    # 此处可后续补充放飞的具体 execute_flight 逻辑调用
                    st.rerun()
            
            with c2:
                st.write("**📦 实盘持仓明细**")
                if pos_table:
                    st.table(pos_table)
                else:
                    st.caption("空仓状态")

with tabs[1]:
    st.subheader("👑 DNA 特征编码孵化器")
    user_cmd = st.text_input("输入孵化指令 (例如：孵化一个激进的末日博弈者):")
    if st.button("🔥 编码 DNA 并孵化"):
        if user_cmd:
            with st.spinner("🧬 正在将指令转化为结构化基因链..."):
                dna_prompt = f"请将指令 '{user_cmd}' 转化为一段结构化的 DNA 特征链。格式要求：特征名:特征值 | 特征名:特征值。例如 Risk:Aggressive | Model:Gamma_Scalp | Mood:Greedy。仅返回字符串。"
                dna_res = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=dna_prompt)
                dna_chain = dna_res.text.strip()
                
                clients['supabase'].table("drones").insert({
                    "name": f"AI-{random.randint(100,999)}", "style": dna_chain,
                    "balance": 100000.0, "total_assets": 100000.0, "portfolio": ["GLD"], "positions": {}
                }).execute()
                st.success("孵化成功！")
                st.rerun()

with tabs[2]:
    if st.button("🗑️ 清空所有工蜂数据"):
        clients['supabase'].table("drones").delete().neq("name", "RESERVED").execute()
        st.rerun()