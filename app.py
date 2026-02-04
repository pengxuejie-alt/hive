import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 核心初始化 (注入鹰眼样式表)
# ==========================================
VERSION = "v13.4 (Eagle Eye Audit)"
st.set_page_config(page_title="Hive 智能金融审计", layout="wide")

st.markdown("""
    <style>
    .audit-card { background-color: #ffffff; padding: 20px; border-radius: 10px; border: 1px solid #eee; }
    .data-text { font-family: monospace; color: #1a73e8; font-weight: bold; }
    .thought-text { font-size: 0.85rem; color: #5f6368; line-height: 1.4; background: #f8f9fa; padding: 10px; border-radius: 5px; }
    .action-text { font-weight: bold; color: #d93025; }
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

def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

# ==========================================
# 2. 行情逻辑 (复刻虎之眼)
# ==========================================
def get_verified_price(poly, ticker):
    try:
        is_option = ticker.startswith("O:") or len(ticker) > 10
        if not is_option:
            snap = poly.get_snapshot_ticker("stocks", ticker)
            prev = poly.get_previous_close_agg(ticker)
            y_close = get_val(prev[0] if prev else None, 'close')
            lt, lq = getattr(snap, 'last_trade', None), getattr(snap, 'last_quote', None)
            tp = get_val(lt, 'p', 'price')
            bp, ap = get_val(lq, 'p', 'bid'), get_val(lq, 'P', 'ask')
            return tp if tp > 0 else (((bp + ap) / 2) if (bp > 0 and ap > 0) else y_close)
        else:
            end = datetime.now()
            start = end - timedelta(days=5)
            aggs = poly.get_aggs(ticker, 1, "minute", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            if aggs:
                for i in range(len(aggs)-1, -1, -1):
                    if aggs[i].volume > 0: return float(aggs[i].close)
            prev = poly.get_previous_close_agg(ticker)
            return float(prev[0].close) if prev else 0.0
    except: return 0.0

# ==========================================
# 3. 🚨 核心：修正后的决策汇报逻辑
# ==========================================
def execute_flight(d, clients):
    dna = d.get('style', 'Risk:Neutral')
    history = (d.get('logs') or [])[:3]
    tk = "GLD"
    curr_p = get_verified_price(clients['poly'], tk)
    
    # 计算当前市值用于 Prompt
    cash, pos = float(d['balance']), d.get('positions', {})
    mv_total = sum([get_verified_price(clients['poly'], s) * q * 100 for s, q in pos.items()])
    nav = cash + mv_total

    prompt = f"""你是{d['name']}。DNA:{dna} | 历史记忆:{history}
    🚨 核心数据核对：
    - {tk} 现价: ${curr_p:.2f}
    - 总资产(NAV): ${nav:,.2f}
    - 现金: ${cash:,.2f} | 持仓总值: ${mv_total:,.2f}
    - 详细持仓: {json.dumps(pos)}

    要求: 
    1. 必须意识到总资产的涨跌，不要在 NAV 减少时盲目乐观。
    2. 严格按 JSON 返回：{{ "data_rpt": "...", "thought": "...", "trades": [...] }}
    """
    
    try:
        r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
        res = json.loads(r.text)
        
        # 结算逻辑 (保持稳定)
        nb, np = cash, pos.copy()
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

        # 🚨 按照用户要求的顺序重构 Log 文本
        log_entry = (
            f"📊 数据: {tk}现价${curr_p:.2f} | NAV:${nav:,.2f} | 现金:${cash:,.2f} | 持仓:${mv_total:,.2f} "
            f"| 🧠 思考: {res.get('thought')} "
            f"| ⚡ 行动: {(' | '.join(exec_logs) if exec_logs else '观望')}"
        )
        
        clients['supabase'].table("drones").update({
            "balance": nb, "positions": np, "patrol_count": d.get('patrol_count', 0)+1,
            "logs": ([log_entry] + (d.get('logs') or []))[:20]
        }).eq("id", d["id"]).execute()
        
        time.sleep(1)
        return True
    except: return False

# ==========================================
# 4. 界面渲染 (增强易读性排版)
# ==========================================
st.title("🐝 Hive 智能金融审计中心")
d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data

for d in d_res:
    with st.container(border=True):
        h_l, h_r = st.columns([5, 1])
        h_l.subheader(f"🐝 {d['name']} | 审计视图")
        if h_r.button(f"🚀 放飞研判", key=f"f_{d['id']}", type="primary", use_container_width=True):
            if execute_flight(d, clients): st.cache_data.clear(); st.rerun()

        # 资产网格 (Metrics)
        cash, pos = float(d.get('balance', 0.0)), d.get('positions', {})
        mv_total, pos_table = 0.0, []
        for sym, qty in pos.items():
            px = get_verified_price(clients['poly'], sym)
            mv = px * qty * (100 if "O:" in sym else 1)
            mv_total += mv
            pos_table.append({"代码": sym, "持仓": f"{qty}手", "市值": f"${mv:,.2f}"})

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("现金", f"${cash:,.2f}")
        m2.metric("持仓估值", f"${mv_total:,.2f}")
        m3.metric("总资产 (NAV)", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
        m4.metric("审计深度", f"{len(d.get('logs') or [])} 条")

        st.divider()
        
        # 📦 组合明细
        st.write("📦 **实时投资组合**")
        if pos_table: st.dataframe(pd.DataFrame(pos_table), hide_index=True, use_container_width=True)
        else: st.caption("空仓")

        st.divider()
        st.write("🧠 **三维度审计记忆 (Data / Thought / Action)**")
        
        # 🚨 强化排版逻辑
        for log in (d.get('logs') or [])[:5]:
            with st.chat_message("assistant", avatar="🐝"):
                parts = log.split(" | ")
                for p in parts:
                    if "📊 数据" in p:
                        # 数据部分：蓝色等宽字体
                        st.markdown(f'<p class="data-text">{p}</p>', unsafe_allow_html=True)
                    elif "🧠 思考" in p:
                        # 思考部分：灰色小号字体，带背景
                        st.markdown(f'<div class="thought-text">{p.replace("🧠 思考:", "")}</div>', unsafe_allow_html=True)
                    elif "⚡ 行动" in p:
                        # 行动部分：红色粗体
                        st.markdown(f'<p class="action-text">{p}</p>', unsafe_allow_html=True)