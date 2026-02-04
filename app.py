import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 核心配置与初始化
# ==========================================
VERSION = "v11.7 (Force Re-sequencing)"
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
# 2. 虎眼级工具函数
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
# 3. 核心：放飞与结算引擎
# ==========================================
def execute_flight_v11(d, slot, clients):
    with slot:
        dna = d.get('style', 'Risk:Neutral')
        history = d.get('logs', [])[:3]
        st.write(f"🚀 **{d['name']} 正在执行 DNA 决策逻辑...**")
        
        # 抓取行情
        tk = "GLD"
        curr_p = get_verified_price(clients['poly'], tk)
        
        prompt = f"""你是交易工蜂 {d['name']}。
        🧬 DNA特征: {dna} | 🧠 历史记忆: {history}
        当前现金: ${d['balance']:,.2f} | 持仓: {d.get('positions')} | {tk}价格: ${curr_p}
        要求：分析历史与DNA，返回 JSON: {{"thought": "...", "trades": [{{"ticker": "代码", "qty": 1, "action": "BUY/SELL"}}]}}
        """
        try:
            r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            
            # 结算逻辑
            nb, np = float(d['balance']), (d.get('positions') or {}).copy()
            for t in decision.get('trades', []):
                sym, qty, act = t['ticker'].upper(), int(t['qty']), t['action'].upper()
                px = get_verified_price(clients['poly'], sym)
                cost = px * qty * (100 if "O:" in sym else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
            
            # 更新数据库
            new_log = f"[{datetime.now().strftime('%H:%M')}] {decision.get('thought', '观望')[:60]}..."
            clients['supabase'].table("drones").update({
                "balance": nb, "positions": np,
                "patrol_count": (d.get('patrol_count', 0) + 1),
                "logs": ([new_log] + (d.get('logs') or []))[:10]
            }).eq("id", d["id"]).execute()
            st.success(f"💭 {d['name']} 决策完毕")
            return True
        except: return False

# ==========================================
# 4. 界面渲染
# ==========================================
st.title("🐝 Hive 智能金融蜂群")
tabs = st.tabs(["🏆 蜂群看板", "👑 DNA 孵化器", "⚙️ 管理"])

with tabs[0]:
    d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | 年龄: {calculate_age(d.get('created_at'))}", expanded=True):
            # 资产卡片
            cash = float(d.get('balance', 100000.0))
            pos = d.get('positions', {})
            mv_total = 0.0
            pos_table = []
            if pos:
                with st.spinner("实时询价中..."):
                    for sym, qty in pos.items():
                        px = get_verified_price(clients['poly'], sym)
                        mv = px * qty * (100 if "O:" in sym else 1)
                        mv_total += mv
                        pos_table.append({"合约": parse_option_symbol(sym), "数量": f"{qty}手", "单价": f"${px:.2f}", "市值": f"${mv:,.2f}"})

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("现金", f"${cash:,.2f}")
            m2.metric("持仓市值", f"${mv_total:,.2f}")
            m3.metric("总资产", f"${cash + mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
            m4.metric("巡逻次数", d.get('patrol_count', 0))

            st.divider()

            # 🧬 DNA & 基因重组按钮
            c_dna, c_act = st.columns([4, 1])
            with c_dna:
                st.write("🧬 **DNA 序列 (Genetic Fragments)**")
                dna_raw = d.get('style', '')
                if " | " in dna_raw:
                    cols_dna = st.columns(len(dna_raw.split(' | ')))
                    for i, f in enumerate(dna_raw.split(' | ')): cols_dna[i].code(f)
                else:
                    st.info(dna_raw)
            
            with c_act:
                st.write("🛠️ **操作**")
                if st.button("🧬 基因重组", key=f"re_force_{d['id']}", type="primary", use_container_width=True):
                    with st.spinner("基因提取中..."):
                        new_dna = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=f"将以下描述重构为 3-5 个用 ' | ' 分隔的 '特征:短语'，严禁长句：{dna_raw}").text.strip()
                        clients['supabase'].table("drones").update({"style": new_dna}).eq("id", d["id"]).execute()
                        st.rerun()

            st.divider()
            c1, c2 = st.columns([1, 1.5])
            with c1:
                st.write("🧠 **长期记忆**")
                with st.container(height=200):
                    for l in (d.get('logs') or []): st.caption(f"• {l}")
                if st.button(f"🚀 单独放飞 {d['name']}", key=f"f_{d['id']}", type="primary", use_container_width=True):
                    if execute_flight_v11(d, st.container(), clients): st.rerun()
            with c2:
                st.write("**📦 实盘持仓明细**")
                if pos_table: st.table(pos_table)
                else: st.caption("空仓状态")

with tabs[1]:
    st.subheader("👑 DNA 特征编码孵化器")
    user_cmd = st.text_input("输入孵化指令:")
    if st.button("🔥 孵化"):
        dna = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=f"将指令'{user_cmd}'转化为'特征:值 | 特征:值'格式DNA短语，5个以内").text.strip()
        clients['supabase'].table("drones").insert({"name": f"AI-{random.randint(100,999)}", "style": dna, "balance": 100000.0, "positions": {}}).execute()
        st.rerun()