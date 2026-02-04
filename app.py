import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd  # 🚨 核心修复：确保 pandas 已导入
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 核心初始化 (复刻虎之眼底层逻辑)
# ==========================================
VERSION = "v12.8 (Professional Audit UX)"
st.set_page_config(page_title="Hive 智能审计系统", layout="wide")

# 注入专业金融风格 CSS
st.markdown("""
    <style>
    .pro-card {
        background-color: #ffffff;
        padding: 25px;
        border-radius: 15px;
        border: 1px solid #eef2f6;
        box-shadow: 0 4px 12px rgba(0,0,0,0.03);
        margin-bottom: 25px;
    }
    .metric-value { font-size: 1.5rem; font-weight: bold; color: #1a1f36; }
    .audit-msg { border-left: 4px solid #d1d9e0; padding-left: 15px; margin-bottom: 15px; }
    </style>
""", unsafe_allow_html=True)

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

# --- 虎之眼专用工具 ---
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

# ==========================================
# 2. 虎之眼取价逻辑 (修复 GLD 行情 0 价格)
# ==========================================
def get_verified_price(poly, ticker):
    try:
        is_option = ticker.startswith("O:") or len(ticker) > 10
        if not is_option:
            # 💡 股票标的 (GLD) 直接穿透快照
            snap = poly.get_snapshot_ticker("stocks", ticker)
            prev = poly.get_previous_close_agg(ticker)
            y_close = get_val(prev[0] if prev else None, 'close')
            lt, lq = getattr(snap, 'last_trade', None), getattr(snap, 'last_quote', None)
            tp = get_val(lt, 'p', 'price')
            bp, ap = get_val(lq, 'p', 'bid'), get_val(lq, 'P', 'ask')
            # 优先级: 成交价 > 买卖中值 > 昨收
            return tp if tp > 0 else (((bp + ap) / 2) if (bp > 0 and ap > 0) else y_close)
        else:
            # 💡 期权合约 Aggs 回溯
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
        return f"{tk} {mm}/{dd} ${int(strike)/1000} {'C' if cp=='C' else 'P'}"
    return symbol

# ==========================================
# 3. 三维度审计决策引擎
# ==========================================
def execute_flight(d, clients):
    dna = d.get('style', 'Risk:Neutral')
    history = (d.get('logs') or [])[:3]
    tk = "GLD"
    curr_p = get_verified_price(clients['poly'], tk)
    
    prompt = f"""你是{d['name']}。DNA:{dna} | 历史:{history}
    数据: 现金${d['balance']}, 持仓{json.dumps(d.get('positions'))}, {tk}现价${curr_p}
    严格按JSON返回汇报: {{"data_rpt":"...", "thought":"...", "trades":[{"ticker":"O:...", "qty":10, "action":"BUY/SELL"}]}}"""
    
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
                exec_logs.append(f"买入{qty}手 {sym} @${px:.2f}")
            elif act == 'SELL' and np.get(sym, 0) >= qty:
                nb += cost; np[sym] -= qty
                if np[sym] <= 0: del np[sym]
                exec_logs.append(f"卖出{qty}手 {sym} @${px:.2f}")

        log_entry = f"📊 数据:{res.get('data_rpt')} | 🧠 思考:{res.get('thought')} | ⚡ 行动:{' | '.join(exec_logs) if exec_logs else '观望'}"
        clients['supabase'].table("drones").update({
            "balance": nb, "positions": np, "patrol_count": d.get('patrol_count', 0)+1,
            "logs": ([log_entry] + (d.get('logs') or []))[:20]
        }).eq("id", d["id"]).execute()
        return True
    except: return False

# ==========================================
# 4. 专业通栏卡片式看板渲染
# ==========================================
st.title("🐝 Hive 智能金融蜂群审计")
tabs = st.tabs(["🏆 蜂群看板", "👑 DNA 孵化器", "⚙️ 管理系统"])

with tabs[0]:
    d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
    for d in d_res:
        with st.container():
            st.markdown(f'<div class="pro-card">', unsafe_allow_html=True)
            
            # 标题与置顶操作
            h_left, h_right = st.columns([5, 1])
            with h_left:
                st.subheader(f"🐝 工蜂实例：{d['name']} (已巡逻 {d.get('patrol_count', 0)} 次)")
            with h_right:
                if st.button(f"🔥 执行研判", key=f"f_{d['id']}", type="primary", use_container_width=True):
                    if execute_flight(d, clients): st.rerun()

            # 资产核心指标
            cash, pos = float(d.get('balance', 0.0)), d.get('positions', {})
            mv_total, pos_table = 0.0, []
            for sym, qty in pos.items():
                px = get_verified_price(clients['poly'], sym)
                mv = px * qty * (100 if "O:" in sym else 1)
                mv_total += mv
                pos_table.append({"代码": parse_symbol(sym), "头寸": f"{qty}手", "单价": f"${px:.2f}", "估值": f"${mv:,.2f}"})

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("可用现金", f"${cash:,.2f}")
            m2.metric("持仓估值", f"${mv_total:,.2f}")
            m3.metric("总资产 (NAV)", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
            m4.metric("审计深度", f"{len(d.get('logs', []))} 条记录")

            st.divider()

            # 中间区域：DNA 与 组合明细
            c_dna, c_pos = st.columns([1, 2.5])
            with c_dna:
                st.write("🧬 **DNA 片段**")
                dna_raw = d.get('style', '')
                if " | " in dna_raw:
                    for frag in dna_raw.split(' | '): st.code(frag)
                else: st.caption(dna_raw)

            with c_pos:
                st.write("📦 **实时投资组合 (Portfolio)**")
                if pos_table:
                    st.dataframe(pd.DataFrame(pos_table), hide_index=True, use_container_width=True)
                else:
                    st.caption("暂无活跃持仓")

            # 底部审计记录 (平铺展示)
            st.divider()
            st.write("🧠 **三维度审计记忆 (最近 5 条轨迹)**")
            logs = d.get('logs') or []
            if logs:
                for log in logs[:5]:
                    parts = log.split(" | ")
                    with st.chat_message("assistant", avatar="🐝"):
                        for p in parts:
                            if "📊 数据" in p: st.markdown(f"**{p}**")
                            elif "🧠 思考" in p: st.caption(p)
                            elif "⚡ 行动" in p:
                                if "买入" in p or "卖出" in p: st.success(p)
                                else: st.warning(p)
            else: st.caption("暂无审计历史")

            st.markdown('</div>', unsafe_allow_html=True)