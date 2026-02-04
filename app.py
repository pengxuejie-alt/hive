import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from google import genai  # 2026 最新 SDK
from polygon import RESTClient

# --- 1. 神经中枢配置 ---
# ⚠️ 根据 google-genai 2.0 SDK 标准，这是目前最通用的 ID
ACTIVE_MODEL = "gemini-2.0-flash" 

def get_config(key): 
    return os.environ.get(key) or st.secrets.get(key)

try:
    S_URL, S_KEY = get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")
    G_KEY, P_KEY = get_config("GEMINI_KEY"), get_config("POLYGON_KEY")
    
    supabase = create_client(S_URL, S_KEY)
    # google-genai SDK 初始化方式
    gen_client = genai.Client(api_key=G_KEY)
    poly_client = RESTClient(api_key=P_KEY)
except Exception as e:
    st.error(f"❌ 蜂巢初始化失败: {e}"); st.stop()

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
                vol = int(get_val(o.day, 'v', 'volume'))
                if vol < 5: continue
                op = get_val(o.last_trade, 'p') if hasattr(o, 'last_trade') else get_val(o.day, 'c')
                if op <= 0: continue
                if o.details.contract_type == 'call': cv += vol
                else: pv += vol
                rows.append({"S": o.details.strike_price, "P": op, "V": vol, "T": o.details.contract_type})
            data["期权数据"] = {"PCR": round(pv/(cv + 1e-5), 2), "信号": sorted(rows, key=lambda x: x['V'], reverse=True)[:5]}
        return data
    except: return {"代码": ticker, "现价": 0}

# --- 3. 演化任务逻辑 ---
def execute_worker_cycle(d):
    t_start = time.time()
    # 使用全宽 status 容器防止 UI 错位
    with st.status(f"🐝 工蜂 [{d['name']}] 任务执行中...", expanded=True) as status:
        try:
            status.write("📡 嗅探实时蜜源...")
            logic = (d.get('logic','') + d.get('persona','')).lower()
            needs_opt = any(x in logic for x in ["期权", "option", "iv"])
            
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(lambda t: fetch_nectar(t, needs_opt), d.get('portfolio', ['GLD'])))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}

            status.write(f"🧠 咨询神经中枢 (`{ACTIVE_MODEL}`)...")
            prompt = f"你是工蜂{d['name']}。基因:{d['persona']}。现金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data, ensure_ascii=False)}。返回纯JSON：{{'trades':[], 'thought':'中文想法', 'learning':'演化记忆'}}"
            
            # 2026 google-genai 标准调用
            r = gen_client.models.generate_content(
                model=ACTIVE_MODEL, 
                contents=prompt, 
                config={'response_mime_type': 'application/json'}
            )
            decision = json.loads(r.text)

            # 结算与同步
            nb, np, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty, act = t.get('ticker', t.get('symbol', '')), t.get('qty', 0), t.get('action', '').upper()
                if not sym or qty <= 0: continue
                px = fetch_nectar(sym, False)['现价']
                cost = float(qty) * float(px) * (100 if "O:" in sym else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"🟢入库 {sym} @{px}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"🔴出库 {sym} @{px}")

            mv = 0.0
            for s, q in np.items(): mv += q * fetch_nectar(s, False)['现价'] * (100 if "O:" in s else 1)
            
            log_str = f"[{datetime.now().strftime('%H:%M:%S')}] {(' | '.join(reports) if reports else '观望')} | 🧠 {decision.get('thought','')}"
            supabase.table("drones").update({"balance": nb, "positions": np, "total_assets": round(nb + mv, 2), "logs": ([log_str] + (d.get('logs') or []))[:20], "patrol_count": (int(d.get('patrol_count') or 0)) + 1, "memory": decision.get('learning', d.get('memory'))}).eq("id", d["id"]).execute()
            
            status.update(label=f"✅ 任务完成 (耗时: {time.time()-t_start:.2f}s)", state="complete")
            return True
        except Exception as e:
            status.update(label=f"❌ 运行异常: {str(e)}", state="error"); return False

# --- 4. 蜂群生态 UI ---
st.set_page_config(page_title="Hive 蜂群生态系统", layout="wide")
st.title("🐝 Hive 蜂群生态系统")

# 顶部核心信息栏
st.info(f"🧬 **神经中枢已锚定标准 ID:** `{ACTIVE_MODEL}`")

d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data

# 全宽“全量放飞”
if d_res:
    if st.button("🔥 全量放飞蜂群", type="primary", use_container_width=True):
        for d in d_res: 
            execute_worker_cycle(d)
            time.sleep(0.4)
        st.rerun()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    for d in (d_res or []):
        with st.expander(f"🐝 {d['name']} | 总资产: ${d.get('total_assets', 0):,.2f}", expanded=True):
            st.caption(f"基因: {d['persona']} | 蓝图: {d['logic']}")
            if st.button(f"🚀 立即放飞", key=f"run_{d['id']}"):
                execute_worker_cycle(d); st.rerun()
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
    if st.button("🔥 清空蜂巢数据"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()