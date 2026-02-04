import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from google import genai
from polygon import RESTClient

# --- 1. 中枢初始化 ---
def get_config(key): return os.environ.get(key) or st.secrets.get(key)

try:
    S_URL, S_KEY = get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")
    G_KEY, P_KEY = get_config("GEMINI_KEY"), get_config("POLYGON_KEY")
    supabase = create_client(S_URL, S_KEY)
    gen_client = genai.Client(api_key=G_KEY)
    poly_client = RESTClient(api_key=P_KEY)
    ACTIVE_BRAIN = "gemini-2.0-flash" 
except Exception as e:
    st.error(f"❌ 蜂巢初始化失败: {e}"); st.stop()

# --- 2. 蜜源采集 (虎之眼逻辑) ---
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

def fetch_nectar(ticker, needs_options=True):
    try:
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        price = get_val(sn, 'price', 'c')
        if price == 0:
            price = get_val(sn.last_trade, 'p') if hasattr(sn, 'last_trade') else get_val(sn.prev_day, 'c')
        data = {"代码": ticker, "现价": price, "涨跌": get_val(sn, 'todays_change_percent')}
        if needs_options and price > 0:
            opts = list(poly_client.list_snapshot_options_chain(ticker, params={"strike_price.gte": price*0.85, "strike_price.lte": price*1.15, "limit": 15}))
            rows, cv, pv = [], 0, 0
            for o in opts:
                vol = int(get_val(o.day, 'v'))
                if vol < 5: continue
                if o.details.contract_type == 'call': cv += vol
                else: pv += vol
                rows.append({"S": o.details.strike_price, "V": vol, "T": o.details.contract_type})
            data["期权"] = {"PCR": round(pv/(cv + 1e-5), 2), "信号": sorted(rows, key=lambda x: x['V'], reverse=True)[:5]}
        return data
    except: return {"代码": ticker, "现价": 0}

# --- 3. 演化逻辑 ---
def execute_worker(d, status_placeholder):
    t_start = time.time()
    try:
        # 1. 嗅探
        status_placeholder.write("📡 嗅探蜜源...")
        is_opt = "期权" in (d.get('logic','') + d.get('persona',''))
        with ThreadPoolExecutor(max_workers=5) as exe:
            results = list(exe.map(lambda t: fetch_nectar(t, is_opt), d.get('portfolio', ['GLD'])))
        nectar_data = {r['代码']: r for r in results if r['现价'] > 0}

        # 2. 研判 (加入退避重试防止 503/429)
        status_placeholder.write("🧠 神经研判...")
        prompt = f"你是工蜂{d['name']}。基因:{d['persona']}。现金:{d['balance']}。行情:{json.dumps(nectar_data, ensure_ascii=False)}。返回JSON：{{'trades':[], 'thought':'中文想法', 'learning':'记忆'}}"
        
        # 简单的重试机制
        for i in range(3):
            try:
                r = gen_client.models.generate_content(model=ACTIVE_BRAIN, contents=prompt, config={'response_mime_type': 'application/json'})
                decision = json.loads(r.text)
                break
            except Exception as e:
                if i == 2: raise e
                time.sleep(2 * (i + 1))

        # 3. 结算
        nb, np, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
        for t in decision.get('trades', []):
            sym, qty, act = t.get('ticker', t.get('symbol', '')), t.get('qty', 0), t.get('action', '').upper()
            if not sym or qty <= 0: continue
            px = fetch_nectar(sym, False)['现价']
            cost = float(qty) * float(px) * (100 if "O:" in sym else 1)
            if act == 'BUY' and nb >= cost:
                nb -= cost; np[sym] = np.get(sym, 0) + qty
                reports.append(f"🟢买入 {sym} @{px}")
            elif act == 'SELL' and np.get(sym, 0) >= qty:
                nb += cost; np[sym] -= qty
                if np[sym] <= 0: del np[sym]
                reports.append(f"🔴卖出 {sym} @{px}")

        # 4. 同步
        mv = 0.0
        for s, q in np.items(): mv += q * fetch_nectar(s, False)['现价'] * (100 if "O:" in s else 1)
        log_str = f"[{datetime.now().strftime('%H:%M:%S')}] {(' | '.join(reports) if reports else '观望')} | 🧠 {decision.get('thought','')}"
        supabase.table("drones").update({"balance": nb, "positions": np, "total_assets": round(nb + mv, 2), "logs": ([log_str] + (d.get('logs') or []))[:20], "patrol_count": (int(d.get('patrol_count') or 0)) + 1, "memory": decision.get('learning', d.get('memory'))}).eq("id", d["id"]).execute()
        
        status_placeholder.success(f"✅ 耗时: {time.time()-t_start:.1f}s")
        return "SUCCESS"
    except Exception as e:
        status_placeholder.error(f"❌ 异常: {str(e)}")
        return "FAILED"

# --- 4. UI 界面 ---
st.set_page_config(page_title="Hive 蜂群生态系统", layout="wide")
st.title("🐝 Hive 蜂群生态系统")
st.caption(f"🧬 神经中枢已锁定标准 ID: `{ACTIVE_BRAIN}`")

d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data

# UI 核心：全量放飞按钮
if d_res:
    if st.button("🔥 全量放飞蜂群", type="primary", use_container_width=True):
        # 使用进度条显示整体进度
        global_progress = st.progress(0)
        for i, d in enumerate(d_res):
            # 💡 关键修改：在这里放飞，但不干扰下方列表的独立性
            # 通过 session_state 触发刷新效果
            st.session_state[f"run_state_{d['id']}"] = "RUNNING"
            execute_worker(d, st.empty()) # 简单的静默演化，刷新后在列表中看结果
            global_progress.progress((i + 1) / len(d_res))
            time.sleep(0.5)
        st.rerun()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 蜂巢管理"])

with tabs[0]:
    for d in (d_res or []):
        # 💡 UI 优化：标题栏显示状态和最近动向
        last_log = d.get('logs', ["未开始演化"])[0][:30] + "..."
        expander_label = f"🐝 {d['name']} | 资产: ${d.get('total_assets', 0):,.2f} | 最近: {last_log}"
        
        # 默认不展开 (expanded=False)
        with st.expander(expander_label, expanded=False):
            c1, c2, c3 = st.columns(3)
            c1.info(f"🎭 性格基因: {d['persona']}")
            c2.info(f"🧬 逻辑蓝图: {d['logic']}")
            c3.info(f"💾 演化记忆: {d['memory']}")
            
            # 单体放飞
            col_act, col_msg = st.columns([1, 3])
            status_ph = col_msg.empty()
            if col_act.button(f"🚀 立即放飞", key=f"run_{d['id']}"):
                execute_worker(d, status_ph)
                time.sleep(1)
                st.rerun()
            
            st.metric("可用现金", f"${d['balance']:,.2f}")
            if d.get('positions'): st.json(d['positions'])
            for l in (d.get('logs') or [])[:5]: st.caption(l)

# 孵化与管理 (复用之前逻辑)
with tabs[1]:
    instr = st.text_area("输入中文孵化指令:")
    if st.button("开始孵化"):
        p = f"设计JSON：{{'name':'','logic':'','persona':'','portfolio':['GLD']}}。内容中文。指令：{instr}"
        r = gen_client.models.generate_content(model=ACTIVE_BRAIN, contents=p, config={'response_mime_type': 'application/json'})
        item = json.loads(r.text)
        item.update({"balance": 100000.0, "total_assets": 100000.0, "created_at": datetime.now(timezone.utc).isoformat(), "logs": ["已诞生"], "positions": {}})
        supabase.table("drones").insert(item).execute(); st.rerun()

with tabs[2]:
    if st.button("🔥 清空蜂巢数据"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()