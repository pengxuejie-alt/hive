import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from google import genai
from polygon import RESTClient

# --- 1. 环境与大脑配置 ---
# 🚀 修正为预览版 ID，对齐 1000 RPM 配额
VERSION = "v3.5 (Preview Edition)"
ACTIVE_BRAIN = "gemini-3-flash-preview" 

def get_config(key): return os.environ.get(key) or st.secrets.get(key)

try:
    S_URL, S_KEY = get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")
    G_KEY, P_KEY = get_config("GEMINI_KEY"), get_config("POLYGON_KEY")
    supabase = create_client(S_URL, S_KEY)
    gen_client = genai.Client(api_key=G_KEY)
    poly_client = RESTClient(api_key=P_KEY)
except Exception as e:
    st.error(f"❌ 蜂巢初始化失败: {e}"); st.stop()

# --- 2. 神经调度引擎 (重试与解析保护) ---
def safe_brain_decision(prompt):
    for attempt in range(3):
        try:
            time.sleep(random.uniform(0.2, 0.5))
            r = gen_client.models.generate_content(
                model=ACTIVE_BRAIN, 
                contents=prompt, 
                config={'response_mime_type': 'application/json'}
            )
            # 处理可能的结构化返回
            data = json.loads(r.text)
            if isinstance(data, list): data = data[0]
            return data
        except Exception as e:
            if "404" in str(e):
                st.error(f"⚠️ ID 映射失效: {ACTIVE_BRAIN} 无法识别。请确认 API 版本。")
                st.stop()
            if "429" in str(e) and attempt < 2:
                wait = (attempt + 1) * 2
                st.toast(f"⏳ 拥堵避让 {wait}s...", icon="🧠")
                time.sleep(wait)
                continue
            raise e

# --- 3. 价格穿透采集 ---
def fetch_nectar(ticker):
    try:
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        price = getattr(sn, 'price', 0)
        if price == 0:
            price = getattr(sn.last_trade, 'p', 0) if hasattr(sn, 'last_trade') else getattr(sn.prev_day, 'c', 0)
        return {"代码": ticker, "现价": price, "涨跌%": round(getattr(sn, 'todays_change_percent', 0), 2)}
    except: return {"代码": ticker, "现价": 0, "状态": "超时"}

# --- 4. 演化任务 ---
def execute_worker_cycle(d, status_container):
    t_start = time.time()
    try:
        with status_container:
            st.write("📡 **正在穿透市场嗅探行情...**")
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(fetch_nectar, d.get('portfolio', ['GLD'])))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            st.json(nectar_data)

            st.write(f"🧠 **神经研判中 (`{ACTIVE_BRAIN}`)...**")
            prompt = f"你是工蜂{d['name']}。基因:{d['persona']}。现金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data, ensure_ascii=False)}。返回JSON交易指令。"
            
            decision = safe_brain_decision(prompt)

            # 结算
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
        status_container.error(f"❌ 运行崩溃: {str(e)}")
        return False

# --- 5. UI 界面 ---
st.set_page_config(page_title="Hive 蜂群系统", layout="wide")

h1, h2 = st.columns([4, 1])
with h1:
    st.title(f"🐝 Hive 蜂群生态系统 `{VERSION}`")
    st.caption(f"🧠 大脑型号: `{ACTIVE_BRAIN}` | 🛡️ 已开启 1000 RPM 配额对齐")
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
    instr = st.text_area("输入孵化指令:")
    if st.button("开始注入基因"):
        with st.spinner("🧬 蜂后链接中枢中..."):
            try:
                p = f"设计JSON：{{'name':'','logic':'','persona':'','portfolio':['GLD']}}。内容中文。指令：{instr}"
                item = safe_brain_decision(p)
                item.update({
                    "balance": 100000.0, "total_assets": 100000.0, 
                    "created_at": datetime.now(timezone.utc).isoformat(), 
                    "logs": ["已诞生"], "positions": {}
                })
                supabase.table("drones").insert(item).execute()
                st.success(f"✅ {item['name']} 成功孵化！")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"❌ 孵化失败: {str(e)}")

with tabs[2]:
    if st.button("🔥 重置系统"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()