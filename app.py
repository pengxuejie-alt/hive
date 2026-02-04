import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 核心初始化 (保持虎之眼架构)
# ==========================================
VERSION = "v13.3 (Live Sync Edition)"
st.set_page_config(page_title="Hive 智能审计中心", layout="wide")

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
# 2. 行情逻辑 (已验证无需修改)
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
# 3. 🚨 核心：决策与强制同步逻辑
# ==========================================
def execute_flight(d, clients):
    dna = d.get('style', 'Risk:Neutral')
    history = (d.get('logs') or [])[:3]
    tk = "GLD"
    curr_p = get_verified_price(clients['poly'], tk)
    
    prompt = f"""你是{d['name']}。性格DNA:{dna} | 历史:{history}
    现状: 现金${d['balance']:.2f}, 持仓{json.dumps(d.get('positions'))}, {tk}现价${curr_p:.2f}
    严格按 JSON 返回汇报：{{ "data_rpt": "...", "thought": "...", "trades": [{{"ticker": "O:代码", "qty": 10, "action": "BUY/SELL"}}] }}"""
    
    try:
        r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
        res = json.loads(r.text)
        
        # 模拟成交结算
        nb, np = float(d['balance']), (d.get('positions') or {}).copy()
        exec_logs = []
        for t in res.get('trades', []):
            sym, qty, act = t['ticker'].upper(), int(t['qty']), t['action'].upper()
            px = get_verified_price(clients['poly'], sym)
            if px <= 0: continue
            
            cost = px * qty * (100 if "O:" in sym else 1)
            if act == 'BUY' and nb >= cost:
                nb -= cost; np[sym] = np.get(sym, 0) + qty
                exec_logs.append(f"买入 {qty}手 {sym} @${px:.2f}")
            elif act == 'SELL' and np.get(sym, 0) >= qty:
                nb += cost; np[sym] -= qty
                if np[sym] <= 0: del np[sym]
                exec_logs.append(f"卖出 {qty}手 {sym} @${px:.2f}")

        # 构造审计日志
        act_summary = " | ".join(exec_logs) if exec_logs else "持仓观望"
        log_entry = f"📊 数据:{tk}现价${curr_p:.2f} | {res.get('data_rpt')} | 🧠 思考:{res.get('thought')} | ⚡ 行动:{act_summary}"
        
        # 🚨 强制同步：更新 Supabase
        clients['supabase'].table("drones").update({
            "balance": nb, 
            "positions": np, 
            "patrol_count": d.get('patrol_count', 0) + 1,
            "logs": ([log_entry] + (d.get('logs') or []))[:20]
        }).eq("id", d["id"]).execute()
        
        # 弹出提示并等待，给云端数据库一点反映时间
        st.toast(f"✅ {d['name']} 交易已上链更新")
        time.sleep(1) 
        return True
    except Exception as e:
        st.error(f"决策引擎执行失败: {e}")
        return False

# ==========================================
# 4. 专业通栏卡片 UI
# ==========================================
st.title("🐝 Hive 智能金融审计中心")

# 获取最新数据，显式不使用缓存
d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data

for d in d_res:
    with st.container(border=True):
        # 顶部栏
        h_l, h_r = st.columns([5, 1])
        h_l.subheader(f"🐝 {d['name']} (巡逻次数: {d.get('patrol_count', 0)})")
        if h_r.button(f"🚀 放飞研判", key=f"f_{d['id']}", type="primary", use_container_width=True):
            if execute_flight(d, clients):
                st.cache_data.clear() # 强制清理前端所有缓存数据
                st.rerun() # 重新拉取

        # 资产网格
        cash, pos = float(d.get('balance', 0.0)), d.get('positions', {})
        mv_total, pos_table = 0.0, []
        for sym, qty in pos.items():
            px = get_verified_price(clients['poly'], sym)
            mv = px * qty * (100 if "O:" in sym else 1)
            mv_total += mv
            pos_table.append({"代码": sym, "数量": f"{qty}手", "单价": f"${px:.2f}", "市值": f"${mv:,.2f}"})

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("现金 (Cash)", f"${cash:,.2f}")
        m2.metric("持仓市值", f"${mv_total:,.2f}")
        m3.metric("总资产 (NAV)", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
        m4.metric("记忆深度", f"{len(d.get('logs') or [])} 条")

        st.divider()
        
        # 实时投资组合
        st.write("📦 **实时投资组合 (Portfolio)**")
        if pos_table:
            st.dataframe(pd.DataFrame(pos_table), hide_index=True, use_container_width=True)
        else:
            st.caption("空仓状态")

        # 审计日志
        st.divider()
        st.write("🧠 **三维度审计记忆 (Data / Thought / Action)**")
        for log in (d.get('logs') or [])[:5]:
            with st.chat_message("assistant", avatar="🐝"):
                st.markdown(log)