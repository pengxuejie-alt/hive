import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from google import genai
from polygon import RESTClient

# --- 1. 中枢配置 ---
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

# --- 2. 蜜源采集 ---
def fetch_nectar(ticker, needs_options=True):
    try:
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        price = getattr(sn, 'price', 0) or (getattr(sn.last_trade, 'p', 0) if hasattr(sn, 'last_trade') else getattr(sn.prev_day, 'c', 0))
        data = {"代码": ticker, "现价": price, "涨跌": getattr(sn, 'todays_change_percent', 0)}
        if needs_options and price > 0:
            opts = list(poly_client.list_snapshot_options_chain(ticker, params={"limit": 8}))
            data["期权概况"] = f"发现 {len(opts)} 条链"
        return data
    except: return {"代码": ticker, "现价": 0}

# --- 3. 核心演化逻辑 ---
def execute_worker_cycle(d, status_container):
    """
    在指定的 status_container 中运行，不影响外部 UI 结构
    """
    t_start = time.time()
    try:
        with status_container:
            st.write("📡 **正在嗅探实时行情...**")
            logic = (d.get('logic','') + d.get('persona','')).lower()
            needs_opt = "期权" in logic
            
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(lambda t: fetch_nectar(t, needs_opt), d.get('portfolio', ['GLD'])))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            
            # 💡 解决“行情未知”：在这里强制显示读到的数据
            if nectar_data:
                st.code(json.dumps(nectar_data, ensure_ascii=False, indent=2), language="json")
            else:
                st.warning("⚠️ 未能获取到任何有效行情，请检查 Polygon API")

            st.write(f"🧠 **神经研判中 (`{ACTIVE_BRAIN}`)...**")
            prompt = f"你是工蜂{d['name']}。基因:{d['persona']}。现金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data, ensure_ascii=False)}。返回纯JSON：{{'trades':[], 'thought':'中文想法', 'learning':'演化记忆'}}"
            
            # 带有重试的决策
            for i in range(2):
                try:
                    r = gen_client.models.generate_content(model=ACTIVE_BRAIN, contents=prompt, config={'response_mime_type': 'application/json'})
                    decision = json.loads(r.text)
                    break
                except:
                    if i == 1: raise Exception("大脑响应超时")
                    time.sleep(2)

            # 结算逻辑
            nb, np, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty, act = t.get('ticker', t.get('symbol', '')), t.get('qty', 0), t.get('action', '').upper()
                if not sym or qty <= 0: continue
                px = fetch_nectar(sym, False)['现价']
                cost = float(qty) * float(px) * (100 if "O:" in sym else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"🟢买入 {sym}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"🔴卖出 {sym}")

            mv = 0.0
            for s, q in np.items(): mv += q * fetch_nectar(s, False)['现价'] * (100 if "O:" in s else 1)
            
            log_str = f"[{datetime.now().strftime('%H:%M:%S')}] {(' | '.join(reports) if reports else '观望')} | 🧠 {decision.get('thought','')}"
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([log_str] + (d.get('logs') or []))[:20],
                "memory": decision.get('learning', d.get('memory'))
            }).eq("id", d["id"]).execute()
            
            st.success(f"✅ 演化完成 ({time.time()-t_start:.1f}s)")
            return True
    except Exception as e:
        status_container.error(f"❌ 异常: {str(e)}")
        return False

# --- 4. UI 界面 ---
st.set_page_config(page_title="Hive 蜂群生态", layout="wide")

# 标题栏：按钮瘦身并置于右上角
head_col1, head_col2 = st.columns([4, 1])
with head_col1:
    st.title("🐝 Hive 蜂群生态系统")
    st.caption(f"🧬 核心大脑: `{ACTIVE_BRAIN}`")
with head_col2:
    st.write(" ") # 间距对齐
    full_fly = st.button("🔥 全量放飞", type="primary", use_container_width=True)

d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data

# 如果点击全量放飞，我们直接在列表循环中执行，不改变整体布局
if full_fly and d_res:
    progress_bar = st.progress(0)
    # 创建一个占位符字典，用于在下方列表中显示状态
    for i, d in enumerate(d_res):
        st.session_state[f"active_{d['id']}"] = True
        progress_bar.progress((i + 1) / len(d_res))
    # 这里的 logic 会让页面在下面循环时逐个跑

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 蜂巢管理"])

with tabs[0]:
    if not d_res: st.info("请先孵化工蜂。")
    for d in (d_res or []):
        tot = d.get('total_assets', 0)
        cash = d.get('balance', 0)
        pos_val = tot - cash
        last_log = d.get('logs', ["尚未放飞"])[0][:40] + "..."
        
        label = f"🐝 {d['name']} | 资产: ${tot:,.2f} | 现金: ${cash:,.2f} | 持仓: ${pos_val:,.2f} | 最近: {last_log}"
        
        # 💡 点击全量放飞后，对应的工蜂展开显示进度
        is_running = st.session_state.get(f"active_{d['id']}", False)
        
        with st.expander(label, expanded=is_running):
            status_slot = st.container() # 专门用于显示运行状态的容器
            
            col_a, col_b = st.columns([1, 4])
            if col_a.button(f"🚀 单独放飞", key=f"single_{d['id']}") or is_running:
                # 执行演化
                execute_worker_cycle(d, status_slot)
                # 运行完清除状态，防止下次刷新还自动展开
                if is_running: st.session_state[f"active_{d['id']}"] = False
                
            st.json(d.get('positions', {}))
            for l in (d.get('logs') or [])[:5]: st.caption(l)

with tabs[1]:
    instr = st.text_area("孵化指令:")
    if st.button("注入基因"):
        p = f"设计JSON：{{'name':'','logic':'','persona':'','portfolio':['GLD']}}。内容中文。指令：{instr}"
        r = gen_client.models.generate_content(model=ACTIVE_BRAIN, contents=p, config={'response_mime_type': 'application/json'})
        item = json.loads(r.text)
        item.update({"balance": 100000.0, "total_assets": 100000.0, "created_at": datetime.now(timezone.utc).isoformat(), "logs": ["诞生"], "positions": {}})
        supabase.table("drones").insert(item).execute(); st.rerun()

with tabs[2]:
    if st.button("🔥 清空数据"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()