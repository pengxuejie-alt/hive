import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from google import genai
from polygon import RESTClient

# --- 1. 环境与大脑配置 ---
VERSION = "v3.6 (Cluster Pro)"
ACTIVE_BRAIN = "gemini-2.0-flash" # 建议先用 2.0 确保 404 不再发生，若想试 preview 可改回

def get_config(key): return os.environ.get(key) or st.secrets.get(key)

try:
    S_URL, S_KEY = get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")
    G_KEY, P_KEY = get_config("GEMINI_KEY"), get_config("POLYGON_KEY")
    supabase = create_client(S_URL, S_KEY)
    gen_client = genai.Client(api_key=G_KEY)
    poly_client = RESTClient(api_key=P_KEY)
except Exception as e:
    st.error(f"❌ 蜂巢初始化失败: {e}"); st.stop()

# --- 2. 神经调度引擎 (付费版并发优化) ---
def safe_brain_decision(prompt):
    """
    针对付费 1000 RPM 优化的调度器
    加入指数退避重试，即使瞬间并发 5 只也能稳住
    """
    for attempt in range(3):
        try:
            # 即使付费也有微秒级 Burst 限制，加入极小抖动
            time.sleep(random.uniform(0.1, 0.3))
            r = gen_client.models.generate_content(
                model=ACTIVE_BRAIN, 
                contents=prompt, 
                config={'response_mime_type': 'application/json'}
            )
            data = json.loads(r.text)
            return data[0] if isinstance(data, list) else data
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                wait = (attempt + 1) * 2
                st.toast(f"⏳ 神经拥堵，避让 {wait}s...", icon="🧠")
                time.sleep(wait)
                continue
            raise e

# --- 3. 行情穿透采集 ---
def fetch_nectar(ticker):
    try:
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        price = getattr(sn, 'price', 0)
        if price == 0:
            price = getattr(sn.last_trade, 'p', 0) if hasattr(sn, 'last_trade') else getattr(sn.prev_day, 'c', 0)
        return {"代码": ticker, "现价": price, "涨跌%": round(getattr(sn, 'todays_change_percent', 0), 2)}
    except: return {"代码": ticker, "现价": 0}

# --- 4. 演化任务 ---
def execute_worker_cycle(d, status_container):
    t_start = time.time()
    try:
        with status_container:
            st.write("📡 **多源行情嗅探...**")
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(fetch_nectar, d.get('portfolio', ['GLD'])))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            st.json(nectar_data)

            st.write(f"🧠 **神经研判 (`{ACTIVE_BRAIN}`)...**")
            prompt = f"你是工蜂{d['name']}。基因:{d['persona']}。现金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data, ensure_ascii=False)}。返回指令JSON。"
            
            decision = safe_brain_decision(prompt)

            nb, np, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty, act = t.get('ticker', t.get('symbol', '')), t.get('qty', 0), t.get('action', '').upper()
                if not sym or qty <= 0: continue
                px = fetch_nectar(sym)['现价']
                cost = float(qty) * float(px) * (100 if "O:" in sym else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"🟢买入 {sym}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"🔴卖出 {sym}")

            mv = 0.0
            for s, q in np.items(): mv += q * fetch_nectar(s)['现价'] * (100 if "O:" in s else 1)
            
            log_str = f"[{datetime.now().strftime('%H:%M:%S')}] {(' | '.join(reports) if reports else '观望')} | 🧠 {decision.get('thought','')}"
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([log_str] + (d.get('logs') or []))[:20],
                "memory": decision.get('learning', d.get('memory'))
            }).eq("id", d["id"]).execute()
            
            st.success(f"✅ 完成 ({time.time()-t_start:.1f}s)")
            return True
    except Exception as e:
        status_container.error(f"❌ 崩溃: {str(e)}")
        return False

# --- 5. UI 界面 ---
st.set_page_config(page_title="Hive 蜂群集群版", layout="wide")

h1, h2 = st.columns([4, 1])
with h1:
    st.title(f"🐝 Hive 蜂群生态系统 `{VERSION}`")
    st.caption(f"🧠 核心大脑: `{ACTIVE_BRAIN}` | 🛡️ 并发带宽: 1000 RPM")
with h2:
    st.write(" ")
    full_fly = st.button("🔥 全量放飞", type="primary", use_container_width=True)

d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data

if full_fly and d_res:
    for d in d_res: st.session_state[f"run_{d['id']}"] = True

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res: st.info("请先孵化新工蜂。")
    for d in (d_res or []):
        tot, cash = d.get('total_assets', 0), d.get('balance', 0)
        label = f"🐝 {d['name']} | 资产: ${tot:,.2f} | 现金: ${cash:,.2f} | 最近: {d.get('logs', ['-'])[0][:40]}"
        is_active = st.session_state.get(f"run_{d['id']}", False)
        with st.expander(label, expanded=is_active):
            run_slot = st.container()
            if st.button(f"🚀 立即放飞", key=f"btn_{d['id']}") or is_active:
                execute_worker_cycle(d, run_slot)
                if is_active: st.session_state[f"run_{d['id']}"] = False
                st.rerun()
            if d.get('positions'): st.json(d['positions'])
            for l in (d.get('logs') or [])[:5]: st.caption(l)

with tabs[1]:
    st.subheader("👑 蜂后集群孵化")
    col_l, col_r = st.columns([3, 1])
    with col_l:
        instr = st.text_area("孵化指令 (例如：批量孵化3只德州之神工蜂):")
    with col_r:
        batch_count = st.number_input("孵化数量", min_value=1, max_value=5, value=3)
    
    if st.button("🔥 启动集群孵化"):
        if not instr:
            st.warning("请先输入指令")
        else:
            with st.spinner(f"🧬 蜂后正在并行孵化 {batch_count} 只工蜂..."):
                def spawn_one(idx):
                    p = f"设计一个工蜂JSON：{{'name':'','logic':'','persona':'','portfolio':['GLD']}}。内容中文。指令：{instr}。索引：{idx}"
                    try:
                        item = safe_brain_decision(p)
                        if item:
                            item.update({
                                "balance": 100000.0, "total_assets": 100000.0, 
                                "created_at": datetime.now(timezone.utc).isoformat(), 
                                "logs": ["集群孵化诞生"], "positions": {}
                            })
                            supabase.table("drones").insert(item).execute()
                            return item.get('name')
                    except: return None

                with ThreadPoolExecutor(max_workers=batch_count) as executor:
                    names = list(executor.map(spawn_one, range(batch_count)))
                
                st.success(f"✅ 已成功入库: {', '.join(filter(None, names))}")
                time.sleep(1)
                st.rerun()

with tabs[2]:
    if st.button("🔥 重置系统"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()