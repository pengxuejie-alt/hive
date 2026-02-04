import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from google import genai
from polygon import RESTClient

# --- 1. 神经中枢：动态探测 ---
def get_config(key): 
    return os.environ.get(key) or st.secrets.get(key)

try:
    G_KEY = get_config("GEMINI_KEY")
    gen_client = genai.Client(api_key=G_KEY)
    
    # 💡 动态获取当前 API Key 真正支持的所有模型列表
    available_models = [m.name for m in gen_client.models.list() if "generateContent" in m.supported_methods]
    # 优先选择 2.0-flash，其次 1.5-flash
    if any("gemini-2.0-flash" in m for m in available_models):
        ACTIVE_MODEL = "gemini-2.0-flash-exp"
    else:
        ACTIVE_MODEL = "gemini-1.5-flash"
        
    S_URL, S_KEY = get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")
    P_KEY = get_config("POLYGON_KEY")
    supabase = create_client(S_URL, S_KEY)
    poly_client = RESTClient(api_key=P_KEY)
except Exception as e:
    st.error(f"蜂群大脑连接中断: {e}")
    st.stop()

# --- 2. 蜜源采集 (对齐虎之眼高效逻辑) ---
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

def fetch_nectar(ticker, needs_options=True):
    try:
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        # 盘前价格穿透逻辑
        price = get_val(sn, 'price', 'c')
        if price == 0:
            price = get_val(sn.last_trade, 'p') if hasattr(sn, 'last_trade') else get_val(sn.prev_day, 'c')
        
        data = {"代码": ticker, "现价": price, "涨跌": get_val(sn, 'todays_change_percent')}
        
        if needs_options and price > 0:
            # 锁定核心区域 ±15% Strike
            opts = list(poly_client.list_snapshot_options_chain(
                ticker, params={"strike_price.gte": price*0.85, "strike_price.lte": price*1.15, "limit": 15}
            ))
            rows, cv, pv = [], 0, 0
            for o in opts:
                vol = int(get_val(o.day, 'v'))
                if vol < 5: continue
                if o.details.contract_type == 'call': cv += vol
                else: pv += vol
                rows.append({"S": o.details.strike_price, "V": vol, "T": o.details.contract_type})
            data["期权简报"] = {"PCR": round(pv/(cv + 1e-5), 2), "活跃数": len(rows)}
        return data
    except: return {"代码": ticker, "现价": 0}

# --- 3. 演化任务 ---
def run_evolution(d):
    t_start = time.time()
    with st.status(f"🐝 工蜂 [{d['name']}] 采蜜中...", expanded=True) as status:
        try:
            status.write("📡 嗅探实时蜜源...")
            logic = (d.get('logic','') + d.get('persona','')).lower()
            needs_opt = "期权" in logic or "option" in logic
            
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(lambda t: fetch_nectar(t, needs_opt), d.get('portfolio', ['GLD'])))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}

            status.write(f"🧠 咨询神经中枢 (`{ACTIVE_MODEL}`)...")
            prompt = f"你是工蜂{d['name']}。性格:{d['persona']}。资金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data, ensure_ascii=False)}。返回纯JSON：{{'trades':[], 'thought':'中文研判', 'learning':'演化记忆'}}"
            
            # 💡 明确指定当前锚定的模型 ID
            r = gen_client.models.generate_content(
                model=ACTIVE_MODEL, 
                contents=prompt, 
                config={'response_mime_type': 'application/json'}
            )
            decision = json.loads(r.text)

            # 结算逻辑
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

            # 市值同步
            mv = 0.0
            for s, q in np.items(): mv += q * fetch_nectar(s, False)['现价'] * (100 if "O:" in s else 1)
            
            log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] {(' | '.join(reports) if reports else '观望')} | 🧠[{ACTIVE_MODEL}] {decision.get('thought','')}"
            supabase.table("drones").update({"balance": nb, "positions": np, "total_assets": round(nb + mv, 2), "logs": ([log_entry] + (d.get('logs') or []))[:20], "patrol_count": (int(d.get('patrol_count') or 0)) + 1, "memory": decision.get('learning', d.get('memory'))}).eq("id", d["id"]).execute()
            
            status.update(label=f"✅ 任务完成 (耗时: {time.time()-t_start:.2f}s)", state="complete")
            return True
        except Exception as e:
            status.update(label=f"❌ 运行崩溃: {str(e)}", state="error"); return False

# --- 4. UI ---
st.set_page_config(page_title="Hive 蜂群生态", layout="wide")
st.title("🐝 Hive 蜂群生态系统")

# 顶部状态显示
st.info(f"🧬 **神经中枢已锚定最强大脑:** `{ACTIVE_MODEL}` (由 API 实时验证通过)")

d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data

col_t, col_btn = st.columns([3, 1])
with col_t: st.subheader(f"在线工蜂: {len(d_res or [])}")
with col_btn:
    if d_res and st.button("🔥 全量放飞", type="primary", use_container_width=True):
        for d in d_res: run_evolution(d); time.sleep(0.4)
        st.rerun()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 蜂巢管理"])

with tabs[0]:
    for d in (d_res or []):
        with st.expander(f"🐝 {d['name']} | 总资产: ${d.get('total_assets', 0):,.2f}"):
            c1, c2, c3 = st.columns(3)
            c1.info(f"🎭 性格: {d['persona']}"); c2.info(f"🧬 逻辑: {d['logic']}"); c3.info(f"💾 记忆: {d['memory']}")
            if st.button(f"🚀 立即放飞", key=f"run_{d['id']}"):
                run_evolution(d); st.rerun()
            st.metric("可用现金", f"${d['balance']:,.2f}")
            if d.get('positions'): st.json(d['positions'])
            for l in (d.get('logs') or [])[:5]: st.caption(l)

with tabs[1]:
    instr = st.text_area("输入孵化指令:")
    if st.button("开始孵化"):
        p = f"设计JSON：{{'name':'','logic':'','persona':'','portfolio':['GLD']}}。内容中文。指令：{instr}"
        r = gen_client.models.generate_content(model=ACTIVE_MODEL, contents=p, config={'response_mime_type': 'application/json'})
        item = json.loads(r.text)
        item.update({"balance": 100000.0, "total_assets": 100000.0, "created_at": datetime.now(timezone.utc).isoformat(), "logs": ["诞生"], "positions": {}})
        supabase.table("drones").insert(item).execute(); st.rerun()

with tabs[2]:
    if st.button("🔥 清空蜂巢"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()