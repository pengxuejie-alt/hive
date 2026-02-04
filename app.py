import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os, random
from datetime import datetime, timezone
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from google import genai
from polygon import RESTClient

# --- 1. 蜂群中枢初始化 ---
# 锁定 2026 标准模型 ID，不再折腾探测逻辑
MODEL_ID = "gemini-1.5-flash"

def get_config(key): 
    return os.environ.get(key) or st.secrets.get(key)

try:
    S_URL, S_KEY = get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")
    G_KEY, P_KEY = get_config("GEMINI_KEY"), get_config("POLYGON_KEY")
    
    supabase = create_client(S_URL, S_KEY)
    # 使用 Google 官方最新 SDK 结构
    gen_client = genai.Client(api_key=G_KEY)
    poly_client = RESTClient(api_key=P_KEY)
except Exception as e:
    st.error(f"神经中枢连接失败: {e}")
    st.stop()

# --- 2. 蜜源采集 (对齐虎之眼并行逻辑) ---
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

def fetch_nectar(ticker, needs_options=True):
    try:
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        # 深度嗅探价格：实时 > 昨收 > 0
        price = get_val(sn, 'price', 'c')
        if price == 0:
            price = get_val(sn.last_trade, 'p') if hasattr(sn, 'last_trade') else get_val(sn.prev_day, 'c')
        
        data = {"代码": ticker, "现价": price, "涨跌": get_val(sn, 'todays_change_percent')}

        if needs_options and price > 0:
            # 锁定核心区域 ±15% Strike，采样 20 条
            opts = list(poly_client.list_snapshot_options_chain(
                ticker, params={"strike_price.gte": price*0.85, "strike_price.lte": price*1.15, "limit": 20}
            ))
            rows, cv, pv = [], 0, 0
            for o in opts:
                vol = int(get_val(o.day, 'v', 'volume'))
                if vol < 5: continue
                op = get_val(o.last_trade, 'p') if hasattr(o, 'last_trade') else get_val(o.day, 'c')
                if op <= 0: continue
                if o.details.contract_type == 'call': cv += vol
                else: pv += vol
                rows.append({"S": o.details.strike_price, "P": op, "V": vol, "T": o.details.contract_type})
            
            data["期权"] = {"PCR": round(pv/(cv + 1e-5), 2), "异动": sorted(rows, key=lambda x: x['V'], reverse=True)[:5]}
        return data
    except: return {"代码": ticker, "现价": 0}

# --- 3. 演化任务引擎 ---
def execute_worker_cycle(d):
    t_start = time.time()
    with st.status(f"🐝 工蜂 [{d['name']}] 外出采蜜...", expanded=True) as status:
        try:
            # 1. 采集
            status.write("📡 正在穿透市场嗅探蜜源...")
            logic_str = (d.get('logic','') + d.get('persona','')).lower()
            needs_opts = "期权" in logic_str or "option" in logic_str
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(lambda t: fetch_nectar(t, needs_opts), d.get('portfolio', ['GLD'])))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            
            # 2. 研判
            status.write(f"🧠 咨询神经中枢 (Brain: `{MODEL_ID}`)...")
            prompt = f"你是工蜂{d['name']}。基因:{d['persona']}。资金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data, ensure_ascii=False)}。返回纯JSON：{{'trades':[], 'thought':'中文研判', 'learning':'演化记忆'}}"
            
            r = gen_client.models.generate_content(
                model=MODEL_ID, contents=prompt, 
                config={'response_mime_type': 'application/json'}
            )
            decision = json.loads(r.text)
            status.write(f"✅ 神经元响应成功")

            # 3. 结算执行
            nb, np, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty, act = t.get('ticker', t.get('symbol', '')), t.get('qty', 0), t.get('action', '').upper()
                if not sym or qty <= 0: continue
                px = fetch_nectar(sym, False)['现价']
                cost = float(qty) * float(px) * (100 if "O:" in sym else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"🟢采集入库 {sym} @{px}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"🔴消耗库存 {sym} @{px}")

            # 4. 同步
            mv = 0.0
            for s, q in np.items(): mv += q * fetch_nectar(s, False)['现价'] * (100 if "O:" in s else 1)
            log_str = f"[{datetime.now().strftime('%H:%M:%S')}] {(' | '.join(reports) if reports else '观望')} | 🧠 {decision.get('thought','')}"
            supabase.table("drones").update({"balance": nb, "positions": np, "total_assets": round(nb + mv, 2), "logs": ([log_str] + (d.get('logs') or []))[:20], "patrol_count": (int(d.get('patrol_count') or 0)) + 1, "memory": decision.get('learning', d.get('memory'))}).eq("id", d["id"]).execute()
            
            status.write(f"🏁 任务完成 (耗时: {time.time()-t_start:.2f}s)")
            return True
        except Exception as e:
            status.write(f"❌ 采蜜异常: {str(e)}"); return False

# --- 4. UI 界面 ---
st.set_page_config(page_title="Hive 蜂群生态", layout="wide")
st.title("🐝 Hive 蜂群生态系统")

# 右上角全量放飞布局
d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data
col_t, col_btn = st.columns([3, 1])
with col_t:
    st.caption(f"🧬 神经中枢已锁定: `{MODEL_ID}`")
with col_btn:
    if d_res and st.button("🔥 全量放飞", type="primary", use_container_width=True):
        for d in d_res: execute_worker_cycle(d); time.sleep(0.4)
        st.rerun()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res: st.info("请先孵化工蜂。")
    for d in (d_res or []):
        with st.expander(f"🐝 {d['name']} | 总资产: ${d.get('total_assets', 0):,.2f}"):
            c1, c2, c3 = st.columns(3)
            c1.info(f"🎭 **性格基因**\n\n{d['persona']}")
            c2.info(f"🧬 **逻辑蓝图**\n\n{d['logic']}")
            c3.info(f"💾 **演化记忆**\n\n{d['memory']}")
            if st.button(f"🚀 立即放飞", key=f"run_{d['id']}"):
                execute_worker_cycle(d); st.rerun()
            st.metric("可用现金", f"${d['balance']:,.2f}")
            if d.get('positions'): st.json(d['positions'])
            for l in (d.get('logs') or [])[:5]: st.caption(l)

with tabs[1]:
    instr = st.text_area("孵化指令 (中文):")
    if st.button("开始孵化"):
        p = f"设计JSON：{{'name':'','logic':'','persona':'','portfolio':['GLD']}}。内容中文。指令：{instr}"
        r = gen_client.models.generate_content(model=MODEL_ID, contents=p, config={'response_mime_type': 'application/json'})
        res = json.loads(r.text)
        res.update({"balance": 100000.0, "total_assets": 100000.0, "created_at": datetime.now(timezone.utc).isoformat(), "logs": ["诞生于蜂巢"], "positions": {}})
        supabase.table("drones").insert(res).execute(); st.rerun()

with tabs[2]:
    if st.button("🔥 清空蜂巢"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()