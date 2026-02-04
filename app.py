import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 核心配置与引擎初始化
# ==========================================
VERSION = "v11.4 (Lab & Settlement Edition)"
st.set_page_config(page_title="Hive 智能金融", layout="wide")

@st.cache_resource
def init_hive_engine():
    try:
        return {
            "supabase": create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]),
            "gen_client": genai.Client(api_key=st.secrets["GEMINI_KEY"]),
            "poly": RESTClient(api_key=st.secrets["POLYGON_KEY"])
        }, None
    except Exception as e: return None, str(e)

cl_pkg, err = init_hive_engine()
if err: st.error(f"引擎启动失败: {err}"); st.stop()
clients = cl_pkg

# ==========================================
# 2. 虎眼级工具函数 (行情与解析)
# ==========================================
def parse_option_symbol(symbol):
    if not symbol.startswith("O:"): return symbol
    match = re.match(r"O:([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d+)", symbol)
    if match:
        tk, yy, mm, dd, cp, strike = match.groups()
        strike_val = int(strike) / 1000
        return f"{tk} {mm}/{dd} ${strike_val} {'Call' if cp == 'C' else 'Put'}"
    return symbol

def get_verified_price(poly, symbol):
    ticker = symbol if symbol.startswith("O:") else f"O:{symbol}"
    try:
        end = datetime.now()
        start = end - timedelta(days=3)
        aggs = poly.get_aggs(ticker, 1, "minute", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if aggs: return float(aggs[-1].close)
        daily = poly.get_aggs(ticker, 1, "day", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        return float(daily[-1].close) if daily else 0.01
    except: return 0.01

def calculate_age(created_at_str):
    try:
        created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
        delta = datetime.now(pytz.UTC) - created_at
        if delta.days > 0: return f"{delta.days}天 {delta.seconds // 3600}小时"
        return f"{delta.seconds // 3600}小时"
    except: return "刚刚诞生"

# ==========================================
# 3. 核心：放飞与结算引擎 (核心逻辑)
# ==========================================
def execute_flight_v11(d, slot, clients):
    with slot:
        dna = d.get('style', 'Risk:Neutral')
        history = d.get('logs', [])[:3]
        st.write(f"🚀 **{d['name']} 正在进行 DNA 与 记忆 递归研判...**")
        
        # 抓取标的情报
        tk = "GLD"
        curr_p = get_verified_price(clients['poly'], tk)
        
        # 注入记忆与 DNA 的 Prompt
        prompt = f"""你是交易工蜂 {d['name']}。
        🧬 DNA特征: {dna}
        🧠 历史记忆: {history}
        现金: ${d['balance']:,.2f} | 持仓: {d.get('positions')} | {tk}价格: ${curr_p}
        
        要求：
        1. 必须根据历史记忆调整你的贪婪或恐惧。
        2. 返回 JSON: {{"thought": "...", "trades": [{{"ticker": "代码", "qty": 1, "action": "BUY/SELL"}}]}}
        """
        try:
            r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            thought = decision.get('thought', '观望')
            
            # --- 💰 结算系统 ---
            nb, np = float(d['balance']), (d.get('positions') or {}).copy()
            logs = []
            for t in decision.get('trades', []):
                sym, qty, act = t['ticker'].upper(), int(t['qty']), t['action'].upper()
                px = get_verified_price(clients['poly'], sym)
                cost = px * qty * (100 if "O:" in sym else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty; logs.append(f"买入 {qty} {sym}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    logs.append(f"卖出 {qty} {sym}")
            
            # 更新数据库
            new_log = f"[{datetime.now().strftime('%H:%M')}] {thought[:60]}..."
            clients['supabase'].table("drones").update({
                "balance": nb, "positions": np,
                "patrol_count": (d.get('patrol_count', 0) + 1),
                "logs": ([new_log] + (d.get('logs') or []))[:10]
            }).eq("id", d["id"]).execute()
            
            st.success(f"💭 {d['name']} 研判: {thought}")
            return True
        except Exception as e:
            st.error(f"研判异常: {e}"); return False

# ==========================================
# 4. UI 渲染与 Tab 逻辑
# ==========================================
st.title("🐝 Hive 智能金融蜂群")
tabs = st.tabs(["🏆 蜂群看板", "👑 DNA 孵化器", "⚙️ 管理"])

with tabs[0]:
    d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | 年龄: {calculate_age(d.get('created_at'))}", expanded=True):
            # 资产看板展示
            cash = float(d.get('balance', 0.0))
            pos = d.get('positions', {})
            mv_total = 0.0
            pos_table = []
            if pos:
                with st.spinner("实时穿透核算中..."):
                    for sym, qty in pos.items():
                        px = get_verified_price(clients['poly'], sym)
                        mv = px * qty * (100 if "O:" in sym else 1)
                        mv_total += mv
                        pos_table.append({"合约": parse_option_symbol(sym), "数量": f"{qty}手", "单价": f"${px:.2f}", "市值": f"${mv:,.2f}"})

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("现金", f"${cash:,.2f}")
            m2.metric("持仓市值", f"${mv_total:,.2f}")
            m3.metric("总资产", f"${cash + mv_total:,.2f}", delta=f"{( (cash+mv_total)/100000 -1)*100:.2f}%")
            m4.metric("巡逻次数", d.get('patrol_count', 0))

            st.divider()
            # DNA 展示与重组
            st.write("🧬 **DNA 序列**")
            dna_raw = d.get('style', '')
            if " | " in dna_raw:
                cols = st.columns(len(dna_raw.split(' | ')))
                for i, f in enumerate(dna_raw.split(' | ')): cols[i].code(f)
            else:
                c1, c2 = st.columns([4, 1])
                c1.info(dna_raw)
                if c2.button("🧬 基因重组", key=f"re_{d['id']}"):
                    # 调用 Gemini 重组 DNA
                    new_dna = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=f"将以下描述重构为 'Key:Value | Key:Value' 格式短语: {dna_raw}").text.strip()
                    clients['supabase'].table("drones").update({"style": new_dna}).eq("id", d["id"]).execute()
                    st.rerun()

            c1, c2 = st.columns([1, 1.5])
            with c1:
                st.write("🧠 **长期记忆**")
                with st.container(height=200):
                    for l in (d.get('logs') or []): st.caption(f"• {l}")
                if st.button(f"🚀 单独放飞 {d['name']}", key=f"f_{d['id']}", type="primary", use_container_width=True):
                    if execute_flight_v11(d, st.container(), clients): st.rerun()
            with c2:
                st.write("**📦 当前持仓**")
                if pos_table: st.table(pos_table)
                else: st.caption("空仓状态")

with tabs[1]:
    st.subheader("👑 DNA 特征编码孵化器")
    user_cmd = st.text_input("输入孵化指令:")
    if st.button("🔥 孵化"):
        dna = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=f"将指令'{user_cmd}'转化为'Key:Value | Key:Value'格式DNA短语").text.strip()
        clients['supabase'].table("drones").insert({"name": f"AI-{random.randint(100,999)}", "style": dna, "balance": 100000.0, "positions": {}}).execute()
        st.rerun()