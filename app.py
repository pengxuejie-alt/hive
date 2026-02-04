import streamlit as st
import json, time, os, random, re, pytz
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 核心初始化 (复刻虎之眼底层架构)
# ==========================================
VERSION = "v12.1 (Full-Audit Edition)"
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
# 2. 🚨 核心：复刻虎之眼 v6.3.1 取价逻辑 (修复 0 价格)
# ==========================================
def get_verified_price(poly, ticker):
    try:
        # 判断是期权合约还是股票标的
        if ticker.startswith("O:") or len(ticker) > 10:
            # --- 期权：Aggs 分钟线回溯 ---
            end = datetime.now()
            start = end - timedelta(days=5)
            aggs = poly.get_aggs(ticker, 1, "minute", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            if aggs:
                for i in range(len(aggs)-1, -1, -1):
                    if aggs[i].volume > 0: return float(aggs[i].close)
            prev = poly.get_previous_close_agg(ticker)
            return float(prev[0].close) if prev else 0.0
        else:
            # --- 股票：Snapshot 实时快照 (虎之眼核心) ---
            snap = poly.get_snapshot_ticker("stocks", ticker)
            prev = poly.get_previous_close_agg(ticker)
            y_close = get_val(prev[0] if prev else None, 'close')
            
            lt, lq = getattr(snap, 'last_trade', None), getattr(snap, 'last_quote', None)
            tp = get_val(lt, 'p', 'price')
            bp, ap = get_val(lq, 'p', 'bid'), get_val(lq, 'P', 'ask')
            
            # 优先级: 实时成交 > 买卖中值 > 昨日收盘
            return tp if tp > 0 else (((bp + ap) / 2) if (bp > 0 and ap > 0) else y_close)
    except:
        return 0.0

def parse_option_symbol(symbol):
    if not symbol.startswith("O:"): return symbol
    match = re.match(r"O:([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d+)", symbol)
    if match:
        tk, yy, mm, dd, cp, strike = match.groups()
        strike_val = int(strike) / 1000
        return f"{tk} {mm}/{dd} ${strike_val} {'Call' if cp == 'C' else 'Put'}"
    return symbol

# ==========================================
# 3. 🧠 放飞引擎：三维度审计版 (Data/Thought/Action)
# ==========================================
def execute_flight_v12(d, slot, clients):
    with slot:
        dna = d.get('style', 'Risk:Neutral')
        history = (d.get('logs') or [])[:3]
        tk = "GLD"
        curr_p = get_verified_price(clients['poly'], tk)
        
        st.write(f"🚀 **{d['name']} 正在进行深度审计研判...**")
        
        prompt = f"""你是交易工蜂 {d['name']}。
        🧬 DNA特征: {dna} | 🧠 记忆: {history}
        当前数据: 现金 ${d['balance']:,.2f}, 持仓 {json.dumps(d.get('positions'))}, {tk}现价 ${curr_p}
        
        请严格按 JSON 返回：
        {{
          "data_report": "记录关键价格和异动",
          "thought": "基于DNA和记忆的思考过程",
          "action_plan": "具体操作逻辑",
          "trades": [{{"ticker": "O:...", "qty": 10, "action": "BUY/SELL"}}]
        }}
        """
        try:
            r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            res = json.loads(r.text)
            
            nb, np = float(d['balance']), (d.get('positions') or {}).copy()
            execution = []
            for t in res.get('trades', []):
                sym, qty, act = t['ticker'].upper(), int(t['qty']), t['action'].upper()
                px = get_verified_price(clients['poly'], sym)
                if px <= 0: continue
                cost = px * qty * (100 if "O:" in sym else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    execution.append(f"买入 {qty}手 {sym} @${px:.2f}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    execution.append(f"卖出 {qty}手 {sym} @${px:.2f}")

            # 构造三维度标准审计日志
            full_log = (
                f"📊 数据：{res.get('data_report')} | "
                f"🧠 思考：{res.get('thought')} | "
                f"⚡ 行动：{(' | '.join(execution) if execution else '观望')}"
            )
            
            clients['supabase'].table("drones").update({
                "balance": nb, "positions": np,
                "patrol_count": (d.get('patrol_count', 0) + 1),
                "logs": ([full_log] + (d.get('logs') or []))[:20]
            }).eq("id", d["id"]).execute()
            
            st.success(f"✅ {d['name']} 执行完毕")
            return True
        except Exception as e:
            st.error(f"研判执行失败: {e}"); return False

# ==========================================
# 4. UI 渲染：放大版审计看板
# ==========================================
tabs = st.tabs(["🏆 蜂群看板", "👑 DNA 孵化器", "⚙️ 管理"])

with tabs[0]:
    d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | 存活: {len(d.get('logs') or [])} 次巡逻", expanded=True):
            # 顶部资产 Metrics
            cash, pos = float(d.get('balance', 0.0)), d.get('positions', {})
            mv_total, pos_table = 0.0, []
            if pos:
                with st.spinner("同步市值中..."):
                    for sym, qty in pos.items():
                        px = get_verified_price(clients['poly'], sym)
                        mv = px * qty * (100 if "O:" in sym else 1)
                        mv_total += mv
                        pos_table.append({"合约": parse_option_symbol(sym), "数量": f"{qty}手", "单价": f"${px:.4f}", "市值": f"${mv:,.2f}"})

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("现金", f"${cash:,.2f}")
            m2.metric("持仓市值", f"${mv_total:,.2f}")
            m3.metric("总资产", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
            m4.metric("审计深度", f"{len(d.get('logs') or [])} 条")

            st.divider()

            # 🧠 核心：宽屏三维度审计记忆 (放大版)
            st.markdown("### 🧠 三维度审计记忆 (Data / Thought / Action)")
            with st.container(height=500, border=True):
                logs = d.get('logs') or []
                if not logs: st.caption("尚无记录。")
                for l in logs:
                    parts = l.split(" | ")
                    with st.chat_message("assistant", avatar="🐝"):
                        for p in parts:
                            if "📊 数据" in p: st.markdown(f"**{p}**")
                            elif "🧠 思考" in p: st.info(p)
                            elif "⚡ 行动" in p: st.success(p) if "买入" in p or "卖出" in p else st.warning(p)
                    st.divider()

            st.divider()

            # DNA 与 操作与持仓
            c_dna, c_act, c_pos = st.columns([1, 1, 1.5])
            with c_dna:
                st.write("🧬 **DNA 片段**")
                dna_raw = d.get('style', '')
                if " | " in dna_raw:
                    for f in dna_raw.split(' | '): st.code(f)
                else:
                    if st.button("🧬 基因重组", key=f"re_{d['id']}"):
                        new_dna = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=f"重构为短语: {dna_raw}").text.strip()
                        clients['supabase'].table("drones").update({"style": new_dna}).eq("id", d["id"]).execute(); st.rerun()
            
            with c_act:
                st.write("🚀 **指令中心**")
                if st.button(f"🔥 放飞 {d['name']}", key=f"f_{d['id']}", type="primary", use_container_width=True):
                    if execute_flight_v12(d, st.container(), clients): st.rerun()

            with c_pos:
                st.write("📦 **实盘持仓**")
                if pos_table: st.table(pos_table)
                else: st.caption("空仓")

# 孵化器与管理页面逻辑保持稳定...