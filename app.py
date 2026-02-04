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

# --- 2. 蜜源采集 (对齐虎之眼) ---
def fetch_nectar(ticker, needs_options=True):
    try:
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        # 深度寻价：实时 > 昨收 > 0
        price = getattr(sn, 'price', 0)
        if price == 0:
            price = getattr(sn.last_trade, 'p', 0) if hasattr(sn, 'last_trade') else getattr(sn.prev_day, 'c', 0)
        data = {"代码": ticker, "现价": price, "涨跌": getattr(sn, 'todays_change_percent', 0)}
        if needs_options and price > 0:
            # 锁定核心区域 ±10% Strike
            opts = list(poly_client.list_snapshot_options_chain(ticker, params={"strike_price.gte": price*0.9, "strike_price.lte": price*1.1, "limit": 10}))
            data["期权数据"] = f"发现 {len(opts)} 条核心合约"
        return data
    except: return {"代码": ticker, "现价": 0, "错误": "接口超时"}

# --- 3. 核心演化逻辑 ---
def execute_worker_cycle(d, status_container):
    t_start = time.time()
    try:
        with status_container:
            st.write("📡 **正在嗅探实时行情...**")
            logic = (d.get('logic','') + d.get('persona','')).lower()
            needs_opt = "期权" in logic
            
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(lambda t: fetch_nectar(t, needs_opt), d.get('portfolio', ['GLD'])))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            
            # 💡 解决“行情未知”：强制在 UI 打印读取到的原始行情数据
            st.markdown("**🔍 采集到的行情快照:**")
            st.json(nectar_data)

            st.write(f"🧠 **神经研判中 (`{ACTIVE_BRAIN}`)...**")
            prompt = f"你是工蜂{d['name']}。基因:{d['persona']}。现金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data, ensure_ascii=False)}。你必须返回一个纯JSON，包含 trades(列表), thought(中文研判), learning(记忆)。"
            
            # 带有解析保护的决策获取
            response = gen_client.models.generate_content(model=ACTIVE_BRAIN, contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(response.text)
            if isinstance(decision, list): decision = decision[0] # 兼容某些模型返回数组的情况

            # 结算逻辑
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
                    if np.get(sym, 0) <= 0: del np[sym]
                    reports.append(f"🔴出库 {sym} @{px}")

            # 市值同步
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
        status_container.error(f"❌ 运行崩溃: {str(e)}")
        return False

# --- 4. UI 界面 ---
st.set_page_config(page_title="Hive 蜂群系统", layout="wide")

# 标题栏：精简布局
h1, h2 = st.columns([4, 1])
h1.title("🐝 Hive 蜂群生态系统")
h1.caption(f"🧬 核心大脑: `{ACTIVE_BRAIN}`")
full_fly = h2.button("🔥 全量放飞", type="primary", use_container_width=True)

d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data

# 处理全量放飞逻辑 (通过 session_state 控制逐个展开)
if full_fly and d_res:
    for d in d_res:
        st.session_state[f"run_{d['id']}"] = True

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 蜂巢管理"])

with tabs[0]:
    if not d_res: st.info("请先孵化工蜂。")
    for d in (d_res or []):
        tot, cash = d.get('total_assets', 0), d.get('balance', 0)
        label = f"🐝 {d['name']} | 总资产: ${tot:,.2f} | 现金: ${cash:,.2f} | 最近: {d.get('logs', ['-'])[0][:40]}"
        
        is_active = st.session_state.get(f"run_{d['id']}", False)
        
        with st.expander(label, expanded=is_active):
            run_slot = st.container()
            if st.button(f"🚀 单独放飞", key=f"btn_{d['id']}") or is_active:
                execute_worker_cycle(d, run_slot)
                if is_active: st.session_state[f"run_{d['id']}"] = False # 运行完关闭标记
                st.rerun() # 强制重绘以刷新标题栏数据
            
            st.metric("总资产", f"${tot:,.2f}")
            if d.get('positions'): st.json(d['positions'])
            for l in (d.get('logs') or [])[:5]: st.caption(l)

with tabs[1]:
    instr = st.text_area("孵化指令 (例如：孵化一只追求高 alpha 的工蜂):")
    if st.button("开始注入基因"):
        try:
            p = f"设计JSON：{{'name':'','logic':'','persona':'','portfolio':['GLD']}}。内容中文。指令：{instr}"
            r_raw = gen_client.models.generate_content(model=ACTIVE_BRAIN, contents=p, config={'response_mime_type': 'application/json'})
            item = json.loads(r_raw.text)
            
            # 💡 解决 AttributeError：确保 item 是字典
            if isinstance(item, list): item = item[0]
            
            item.update({
                "balance": 100000.0, "total_assets": 100000.0, 
                "created_at": datetime.now(timezone.utc).isoformat(), 
                "logs": ["诞生于蜂巢"], "positions": {}
            })
            supabase.table("drones").insert(item).execute()
            st.success("👑 蜂后已成功孵化新工蜂！")
            st.rerun()
        except Exception as e:
            st.error(f"孵化失败: {str(e)}")

with tabs[2]:
    if st.button("🔥 彻底清空蜂群"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()