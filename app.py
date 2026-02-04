import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 核心初始化 (样式增强)
# ==========================================
VERSION = "v13.5 (Timestamp & Hard Sync)"
st.set_page_config(page_title="Hive 智能金融审计", layout="wide")

st.markdown("""
    <style>
    .audit-card { background-color: #ffffff; padding: 20px; border-radius: 10px; border: 1px solid #eee; }
    .time-tag { color: #999; font-size: 0.8rem; font-weight: normal; }
    .data-text { font-family: monospace; color: #1a73e8; font-weight: bold; font-size: 1rem; }
    .thought-text { font-size: 0.8rem; color: #5f6368; line-height: 1.5; background: #f1f3f4; padding: 12px; border-radius: 8px; border-left: 3px solid #ccc; margin: 8px 0; }
    .action-text { font-weight: bold; color: #d93025; font-size: 0.95rem; }
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
# 2. 行情穿透逻辑
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
# 3. 🚨 核心：带时间戳的审计决策
# ==========================================
def execute_flight(d, clients):
    # 获取当前美东时间用于日志
    est = pytz.timezone('US/Eastern')
    now_time = datetime.now(est).strftime('%m-%d %H:%M:%S')
    
    dna = d.get('style', 'Risk:Neutral')
    history = (d.get('logs') or [])[:3]
    tk = "GLD"
    curr_p = get_verified_price(clients['poly'], tk)
    
    cash, pos = float(d['balance']), d.get('positions', {})
    mv_total = sum([get_verified_price(clients['poly'], s) * q * 100 for s, q in pos.items()])
    nav = cash + mv_total

    prompt = f"""你是{d['name']}。DNA:{dna} | 历史记忆:{history}
    市场底稿：{tk}价:${curr_p:.2f} | NAV:${nav:,.2f} | 现金:${cash:,.2f} | 持仓总值:${mv_total:,.2f}
    持仓明细: {json.dumps(pos)}
    要求: 分析NAV变动及盈亏，严格按JSON返回汇报：{{ "data_rpt": "...", "thought": "...", "trades": [...] }}
    """
    
    try:
        r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
        res = json.loads(r.text)
        
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

        # 🚨 构造带时间戳的 Log 文本
        log_entry = (
            f"🕒 {now_time} | 📊 数据: {tk}现价${curr_p:.2f} | NAV:${nav:,.2f} | 现金:${cash:,.2f} | 持仓:${mv_total:,.2f} "
            f"| 🧠 思考: {res.get('thought')} "
            f"| ⚡ 行动: {(' | '.join(exec_logs) if exec_logs else '观望')}"
        )
        
        # 写入数据库
        clients['supabase'].table("drones").update({
            "balance": nb, "positions": np, "patrol_count": d.get('patrol_count', 0)+1,
            "logs": ([log_entry] + (d.get('logs') or []))[:20]
        }).eq("id", d["id"]).execute()
        
        # 显式等待并清理前端缓存
        time.sleep(1.2)
        return True
    except Exception as e:
        st.error(f"研判异常: {e}")
        return False

# ==========================================
# 4. 界面渲染 (优化排版)
# ==========================================
st.title("🐝 Hive 智能金融审计中心")
d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data

for d in d_res:
    with st.container(border=True):
        h_l, h_r = st.columns([5, 1])
        h_l.subheader(f"🐝 {d['name']} | 巡逻审计")
        if h_r.button(f"🚀 放飞研判", key=f"f_{d['id']}", type="primary", use_container_width=True):
            if execute_flight(d, clients):
                st.cache_data.clear() # 关键：清除数据缓存
                st.rerun()

        # Metrics 网格
        cash, pos = float(d.get('balance', 0.0)), d.get('positions', {})
        mv_total, pos_table = 0.0, []
        for sym, qty in pos.items():
            px = get_verified_price(clients['poly'], sym)
            mv = px * qty * (100 if "O:" in sym else 1)
            mv_total += mv
            pos_table.append({"代码": sym, "持仓": f"{qty}手", "估值": f"${mv:,.2f}"})

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("现金", f"${cash:,.2f}")
        m2.metric("持仓估值", f"${mv_total:,.2f}")
        m3.metric("NAV (总资产)", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
        m4.metric("审计深度", f"{len(d.get('logs') or [])}")

        st.divider()
        st.write("🧠 **审计轨迹 (Data / Thought / Action)**")
        
        # 🚨 强化排版逻辑
        for log in (d.get('logs') or [])[:5]:
            with st.chat_message("assistant", avatar="🐝"):
                parts = log.split(" | ")
                # 第一行显示时间戳和核心数据
                header = parts[0] if len(parts) > 0 else ""
                data_part = parts[1] if len(parts) > 1 else ""
                thought_part = parts[2] if len(parts) > 2 else ""
                action_part = parts[3] if len(parts) > 3 else ""

                st.markdown(f'<span class="time-tag">{header}</span> <span class="data-text">{data_part}</span>', unsafe_allow_html=True)
                
                if thought_part:
                    st.markdown(f'<div class="thought-text">{thought_part.replace("🧠 思考:", "")}</div>', unsafe_allow_html=True)
                
                if action_part:
                    st.markdown(f'<p class="action-text">{action_part}</p>', unsafe_allow_html=True)