import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 样式与引擎初始化 (鹰眼审计版)
# ==========================================
VERSION = "v13.8 (Eagle Eye Pro)"
st.set_page_config(page_title="Hive 智能金融审计", layout="wide")

st.markdown("""
    <style>
    .time-tag { color: #888; font-size: 0.7rem; font-family: monospace; }
    .data-row { color: #1a73e8; font-weight: bold; font-family: monospace; font-size: 0.9rem; margin-top: 4px; border-bottom: 1px solid #f0f0f0; padding-bottom: 2px; }
    .thought-block { font-size: 0.75rem; color: #6c757d; background: #f9f9f9; padding: 10px; border-radius: 6px; border-left: 3px solid #dee2e6; margin: 6px 0; line-height: 1.4; white-space: pre-wrap; }
    .action-row { color: #d93025; font-weight: 800; font-size: 0.85rem; margin-top: 4px; }
    .stMetric { background-color: #ffffff; border: 1px solid #eee; padding: 10px; border-radius: 8px; }
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
# 2. 虎之眼行情逻辑 (标的/期权穿透)
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
# 3. 🚨 核心：修正 Value Error 的决策引擎
# ==========================================
def execute_flight(d, clients):
    est = pytz.timezone('US/Eastern')
    now_tag = datetime.now(est).strftime('%m-%d %H:%M:%S')
    
    dna = d.get('style', 'Risk:Neutral')
    history = (d.get('logs') or [])[:3]
    tk = "GLD"
    curr_p = get_verified_price(clients['poly'], tk)
    
    cash, pos = float(d['balance']), d.get('positions', {})
    mv_total = sum([get_verified_price(clients['poly'], s) * q * 100 for s, q in pos.items()])
    nav = cash + mv_total

    # 💡 关键修正：所有 JSON 大括号必须双写 {{ }}，包含 trades 内部的结构
    prompt = f"""你是{d['name']}。性格DNA:{dna} | 历史记忆:{history}
    🚨 环境底稿：
    - {tk}现价: ${curr_p:.2f} | NAV(总资产): ${nav:,.2f}
    - 现金: ${cash:,.2f} | 持仓总值: ${mv_total:,.2f} | 持仓明细: {json.dumps(pos)}

    要求: 
    1. 关注 NAV 的真实盈亏（本金$100,000），盈利时减仓锁利，亏损时严格控回撤。
    2. 严格按 JSON 返回汇报：
    {{ "thought": "思考逻辑并分段", "trades": [{{ "ticker": "O:...", "qty": 10, "action": "BUY/SELL" }}] }}
    """
    
    try:
        r = clients['gen_client'].models.generate_content(
            model="gemini-2.0-flash", 
            contents=prompt, 
            config={'response_mime_type': 'application/json'}
        )
        res = json.loads(r.text)
        
        nb, np = cash, pos.copy()
        exec_logs = []
        for t in res.get('trades', []):
            sym = (t.get('ticker') or t.get('symbol') or "").upper()
            qty, act = int(t.get('qty', 0)), (t.get('action') or "").upper()
            if not sym or qty <= 0: continue
            
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

        # 🚨 重构 Log 文本：顺序对齐 [行情 -> 总资产 -> 现金 -> 持仓]
        log_entry = (
            f"🕒 {now_tag} | "
            f"📊 {tk}:${curr_p:.2f} | NAV:${nav:,.2f} | 现金:${cash:,.2f} | 持仓:${mv_total:,.2f} | "
            f"🧠 思考: {res.get('thought')} | "
            f"⚡ 行动: {(' | '.join(exec_logs) if exec_logs else '观望')}"
        )
        
        clients['supabase'].table("drones").update({
            "balance": nb, "positions": np, "patrol_count": d.get('patrol_count', 0)+1,
            "logs": ([log_entry] + (d.get('logs') or []))[:20]
        }).eq("id", d["id"]).execute()
        
        time.sleep(1.2)
        return True
    except Exception as e:
        st.error(f"决策引擎解析异常: {e}")
        return False

# ==========================================
# 4. 界面渲染 (专业理财通栏卡片)
# ==========================================
st.title("🐝 Hive 智能金融审计中心")
d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data

for d in d_res:
    with st.container(border=True):
        h_l, h_r = st.columns([5, 1])
        h_l.subheader(f"🐝 {d['name']} | 深度审计视图")
        if h_r.button(f"🚀 放飞研判", key=f"f_{d['id']}", type="primary", use_container_width=True):
            if execute_flight(d, clients): st.cache_data.clear(); st.rerun()

        # 资产网格
        cash, pos = float(d.get('balance', 0.0)), d.get('positions', {})
        mv_total, pos_table = 0.0, []
        for sym, qty in pos.items():
            px = get_verified_price(clients['poly'], sym)
            mv = px * qty * (100 if "O:" in sym else 1)
            mv_total += mv
            pos_table.append({"代码": sym, "持仓": f"{qty}手", "估值": f"${mv:,.2f}"})

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("可用现金", f"${cash:,.2f}")
        m2.metric("持仓估值", f"${mv_total:,.2f}")
        m3.metric("NAV (总资产)", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
        m4.metric("审计深度", f"{len(d.get('logs') or [])} 条")

        st.divider()
        st.write("📦 **实时投资组合 (Portfolio)**")
        if pos_table: st.dataframe(pd.DataFrame(pos_table), hide_index=True, use_container_width=True)
        else: st.caption("当前账户无持仓。")

        st.divider()
        st.write("🧠 **三维度审计记忆 (Data / Thought / Action)**")
        
        for log in (d.get('logs') or [])[:5]:
            with st.chat_message("assistant", avatar="🐝"):
                parts = log.split(" | ")
                if len(parts) < 3:
                    st.caption(log)
                    continue
                
                # 时间戳
                st.markdown(f'<span class="time-tag">{parts[0]}</span>', unsafe_allow_html=True)
                # 数据行 (行情优先)
                st.markdown(f'<div class="data-row">{parts[1]}</div>', unsafe_allow_html=True)
                # 思考块 (分段缩小)
                st.markdown(f'<div class="thought-block">{parts[2].replace("🧠 思考:", "").strip()}</div>', unsafe_allow_html=True)
                # 行动行 (红色)
                ac_p = parts[3] if len(parts) > 3 else "⚡ 行动: 观望"
                st.markdown(f'<div class="action-row">{ac_p}</div>', unsafe_allow_html=True)