import streamlit as st
import json, time, os, random, re, pytz
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 核心初始化 (复刻虎之眼 v6.3.1)
# ==========================================
VERSION = "v12.4 (Full-Width Card Edition)"
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
if err: st.error(err); st.stop()
clients = cl_pkg

def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

# ==========================================
# 2. 虎之眼高精度取价逻辑 (修复 0 价格)
# ==========================================
def get_verified_price(poly, ticker):
    try:
        is_option = ticker.startswith("O:") or len(ticker) > 10
        if not is_option:
            # 💡 股票标的 (GLD) 路径
            snap = poly.get_snapshot_ticker("stocks", ticker)
            prev = poly.get_previous_close_agg(ticker)
            y_close = get_val(prev[0] if prev else None, 'close')
            lt, lq = getattr(snap, 'last_trade', None), getattr(snap, 'last_quote', None)
            tp = get_val(lt, 'p', 'price')
            bp, ap = get_val(lq, 'p', 'bid'), get_val(lq, 'P', 'ask')
            return tp if tp > 0 else (((bp + ap) / 2) if (bp > 0 and ap > 0) else y_close)
        else:
            # 💡 期权合约路径
            end = datetime.now()
            start = end - timedelta(days=5)
            aggs = poly.get_aggs(ticker, 1, "minute", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            if aggs:
                for i in range(len(aggs)-1, -1, -1):
                    if aggs[i].volume > 0: return float(aggs[i].close)
            prev = poly.get_previous_close_agg(ticker)
            return float(prev[0].close) if prev else 0.0
    except: return 0.0

def parse_symbol(symbol):
    if not symbol.startswith("O:"): return symbol
    match = re.match(r"O:([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d+)", symbol)
    if match:
        tk, yy, mm, dd, cp, strike = match.groups()
        return f"{tk} {mm}/{dd} ${int(strike)/1000} {'Call' if cp=='C' else 'Put'}"
    return symbol

# ==========================================
# 3. 决策引擎 (集成三维度审计日志)
# ==========================================
def execute_flight(d, clients):
    dna = d.get('style', 'Risk:Neutral')
    history = (d.get('logs') or [])[:3]
    tk = "GLD"
    curr_p = get_verified_price(clients['poly'], tk)
    
    prompt = f"""你是{d['name']}。DNA:{dna} | 记忆:{history}
    数据: 现金${d['balance']}, 持仓{d.get('positions')}, {tk}现价${curr_p}
    要求: 分析数据，给出思考，执行行动。返回JSON: {{"data_rpt":"...", "thought":"...", "trades":[]}}"""
    
    try:
        r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
        res = json.loads(r.text)
        nb, np = float(d['balance']), (d.get('positions') or {}).copy()
        exec_logs = []
        for t in res.get('trades', []):
            sym, qty, act = t['ticker'].upper(), int(t['qty']), t['action'].upper()
            px = get_verified_price(clients['poly'], sym)
            if px <= 0: continue
            cost = px * qty * (100 if "O:" in sym else 1)
            if act == 'BUY' and nb >= cost:
                nb -= cost; np[sym] = np.get(sym, 0) + qty
                exec_logs.append(f"买入{qty}手 {sym} @{px:.2f}")
            elif act == 'SELL' and np.get(sym, 0) >= qty:
                nb += cost; np[sym] -= qty
                if np[sym] <= 0: del np[sym]
                exec_logs.append(f"卖出{qty}手 {sym} @{px:.2f}")

        log_entry = f"📊 数据:{res.get('data_rpt')} | 🧠 思考:{res.get('thought')} | ⚡ 行动:{' | '.join(exec_logs) if exec_logs else '观望'}"
        clients['supabase'].table("drones").update({
            "balance": nb, "positions": np, "patrol_count": d.get('patrol_count', 0)+1,
            "logs": ([log_entry] + (d.get('logs') or []))[:20]
        }).eq("id", d["id"]).execute()
        return True
    except: return False

# ==========================================
# 4. 界面渲染 (通栏卡片式布局)
# ==========================================
st.title("🐝 Hive 智能金融蜂群")
tabs = st.tabs(["🏆 蜂群看板", "👑 DNA 孵化器", "⚙️ 管理"])

with tabs[0]:
    d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
    for d in d_res:
        # --- 🏆 通栏卡片开始 ---
        with st.container(border=True):
            # 第一行：标题与放飞按钮 (置顶)
            h1, h2 = st.columns([5, 1])
            h1.subheader(f"🐝 {d['name']} | 巡逻 {d.get('patrol_count', 0)} 次")
            if h2.button(f"🔥 立即放飞", key=f"f_{d['id']}", type="primary", use_container_width=True):
                if execute_flight(d, clients): st.rerun()

            # 第二行：资产 Metrics (通栏分布)
            cash, pos = float(d.get('balance', 0.0)), d.get('positions', {})
            mv_total, pos_table = 0.0, []
            for sym, qty in pos.items():
                px = get_verified_price(clients['poly'], sym)
                mv = px * qty * (100 if "O:" in sym else 1)
                mv_total += mv
                pos_table.append({"合约": parse_symbol(sym), "数量": f"{qty}手", "现价": f"${px:.2f}", "市值": f"${mv:,.2f}"})

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("可用现金", f"${cash:,.2f}")
            m2.metric("持仓市值", f"${mv_total:,.2f}")
            m3.metric("总资产", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
            m4.metric("审计深度", f"{len(d.get('logs') or [])} 条")

            # 第三行：DNA 与 持仓明细 (并排)
            st.divider()
            c_dna, c_pos = st.columns([1, 2])
            with c_dna:
                st.write("🧬 **DNA 序列**")
                dna_raw = d.get('style', '')
                if " | " in dna_raw:
                    for f in dna_raw.split(' | '): st.code(f)
                else: 
                    st.caption(dna_raw)
                    if st.button("重组 DNA", key=f"re_{d['id']}"):
                        new_dna = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=f"重构DNA短语: {dna_raw}").text.strip()
                        clients['supabase'].table("drones").update({"style": new_dna}).eq("id", d["id"]).execute(); st.rerun()

            with c_pos:
                st.write("📦 **实时持仓明细**")
                if pos_table: st.dataframe(pd.DataFrame(pos_table), hide_index=True, use_container_width=True)
                else: st.caption("暂无持仓")

            # 第四行：审计记忆 (平铺，不产生内部滚动)
            st.divider()
            st.write("🧠 **最近审计记录 (Data / Thought / Action)**")
            logs = d.get('logs') or []
            if logs:
                for l in logs[:5]: # 只显示最近5条，防止页面过长
                    parts = l.split(" | ")
                    with st.chat_message("assistant", avatar="🐝"):
                        for p in parts:
                            if "📊 数据" in p: st.markdown(f"**{p}**")
                            elif "🧠 思考" in p: st.caption(p)
                            elif "⚡ 行动" in p: 
                                if "买入" in p or "卖出" in p: st.success(p)
                                else: st.warning(p)
            else: st.caption("尚无记录")
            st.write("") # 底部留白

# Tab 1/2 略，保持稳定