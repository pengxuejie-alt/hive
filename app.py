import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from google import genai
from polygon import RESTClient

# --- 1. 环境初始化 ---
VERSION = "v4.1 (Ultra Stable)"
ACTIVE_BRAIN = "gemini-2.0-flash"

def get_config(key): return os.environ.get(key) or st.secrets.get(key)

try:
    S_URL, S_KEY = get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")
    G_KEY, P_KEY = get_config("GEMINI_KEY"), get_config("POLYGON_KEY")
    supabase = create_client(S_URL, S_KEY)
    gen_client = genai.Client(api_key=G_KEY)
    poly_client = RESTClient(api_key=P_KEY)
except Exception as e:
    st.error(f"❌ 蜂巢启动失败: {e}"); st.stop()

# --- 2. 核心功能函数 ---
def safe_brain_decision(prompt):
    """带重试的大脑决策，解决 429 问题"""
    for attempt in range(3):
        try:
            time.sleep(random.uniform(0.1, 0.3))
            r = gen_client.models.generate_content(model=ACTIVE_BRAIN, contents=prompt, config={'response_mime_type': 'application/json'})
            data = json.loads(r.text)
            return data[0] if isinstance(data, list) else data
        except Exception as e:
            if "429" in str(e): time.sleep(2); continue
            raise e

def fetch_nectar(ticker):
    """高可靠行情抓取"""
    try:
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        price = getattr(sn, 'price', 0) or (getattr(sn.last_trade, 'p', 0) if hasattr(sn, 'last_trade') else getattr(sn.prev_day, 'c', 0))
        return {"代码": ticker, "现价": price, "涨跌%": round(getattr(sn, 'todays_change_percent', 0), 2)}
    except: return {"代码": ticker, "现价": 0}

def execute_worker_cycle(d, slot):
    """完整的演化逻辑，包含属性写入"""
    with slot:
        try:
            st.write("📡 **正在读取实时行情...**")
            # 兼容德州之神项目：如果没有 portfolio 则默认看大盘
            targets = d.get('portfolio', ['SPY', 'QQQ'])
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(fetch_nectar, targets))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            
            st.info(f"📊 实时行情快照: {json.dumps(nectar_data, ensure_ascii=False)}")

            st.write(f"🧠 **神经研判决策中...**")
            prompt = f"你是工蜂{d['name']}。基因:{d['persona']}。记忆:{d.get('memory','无')}。现金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data)}。返回JSON：{{'trades':[], 'thought':'', 'learning':''}}"
            decision = safe_brain_decision(prompt)

            # 模拟交易结算
            nb, np, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty, act = t.get('ticker', '').upper(), t.get('qty', 0), t.get('action', '').upper()
                px_data = fetch_nectar(sym)
                if px_data['现价'] <= 0: continue
                cost = qty * px_data['现价'] * (100 if "O:" in sym else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"🟢买入 {sym}@{px_data['现价']}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"🔴卖出 {sym}@{px_data['现价']}")

            # 资产重估
            mv = sum(q * fetch_nectar(s)['现价'] * (100 if "O:" in s else 1) for s, q in np.items())
            
            # 日志持久化
            log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] {(' | '.join(reports) if reports else '观望')} | 🧠 {decision.get('thought','')}"
            new_logs = ([log_entry] + (d.get('logs') or []))[:20]
            
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": new_logs,
                "memory": decision.get('learning', d.get('memory')),
                "fly_count": (d.get('fly_count', 0) + 1)
            }).eq("id", d["id"]).execute()
            st.success("✅ 演化记录已存入档案")
        except Exception as e:
            st.error(f"❌ 执行失败: {e}")

# --- 3. UI 界面 ---
st.set_page_config(page_title="Hive 蜂群面板", layout="wide")

# 顶部栏
h1, h2 = st.columns([4, 1])
h1.title(f"🐝 Hive 蜂群生态系统 `{VERSION}`")
full_fly = h2.button("🔥 全量放飞", type="primary", use_container_width=True)

# 数据加载
d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data
if full_fly and d_res:
    for d in d_res: st.session_state[f"run_{d['id']}"] = True

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

# --- TAB 0: 档案面板 ---
with tabs[0]:
    if not d_res: st.info("请先前往孵化。")
    for d in (d_res or []):
        is_active = st.session_state.get(f"run_{d['id']}", False)
        # 优化标题显示
        header = f"🐝 {d['name']} | 资产: ${d['total_assets']:,.2f} | 现金: ${d['balance']:,.2f} | 次数: {d.get('fly_count',0)}"
        
        with st.expander(header, expanded=is_active):
            col_left, col_right = st.columns([1, 1])
            with col_left:
                st.markdown(f"**🧬 基因/性格:**\n> {d.get('persona', '初始基因')}")
                st.markdown(f"**🧠 长期记忆:**\n> {d.get('memory', '尚无记忆')}")
                st.caption(f"📅 孵化日期: {d.get('created_at', '未知')[:10]}")
            with col_right:
                st.write("**📦 当前仓位数据:**")
                st.json(d.get('positions', {}))
                st.write(f"⚙️ **决策逻辑:** {d.get('logic', '通用策略')}")

            run_slot = st.container()
            if st.button(f"🚀 单独放飞", key=f"f_{d['id']}") or is_active:
                execute_worker_cycle(d, run_slot)
                if is_active: st.session_state[f"run_{d['id']}"] = False
                st.rerun()
            
            st.write("**📜 演化日志 (最近 5 条):**")
            for l in (d.get('logs') or [])[:5]: st.caption(l)

# --- TAB 1: 批量孵化 (修复 APIError) ---
with tabs[1]:
    st.subheader("👑 蜂后集群孵化")
    c1, c2 = st.columns([3, 1])
    instr = c1.text_area("指令 (如：孵化3只德州之神项目专家):", value="德州之神，赌场高手，性格张扬")
    count = c2.number_input("数量", 1, 10, 3)
    
    if st.button("🔥 开始高并发孵化"):
        with st.spinner("🧬 蜂后正在连接神经中枢并合成基因..."):
            def spawn(idx):
                # 💡 解决 APIError 的关键：确保名字绝对不重复
                seed = random.randint(100, 999)
                p = f"设计JSON：{{'name':'3字纯中文名','logic':'','persona':'','portfolio':['GLD']}}。内容中文。指令：{instr}"
                try:
                    item = safe_brain_decision(p)
                    # 强行打上编号后缀，绕过 Supabase Unique Name 约束
                    unique_name = f"{item.get('name', '工蜂')}-{seed}-{idx}"
                    item.update({
                        "name": unique_name,
                        "balance": 100000.0, "total_assets": 100000.0, 
                        "created_at": datetime.now(timezone.utc).isoformat(), 
                        "logs": ["在蜂巢仪式中诞生"], "positions": {}, 
                        "fly_count": 0, "memory": "纯净状态"
                    })
                    supabase.table("drones").insert(item).execute()
                    return unique_name
                except Exception as e:
                    return f"Error: {str(e)}"

            with ThreadPoolExecutor(max_workers=count) as exe:
                names = list(exe.map(spawn, range(count)))
            
            st.success(f"✅ 成功孵化: {', '.join(filter(None, [n for n in names if 'Error' not in n]))}")
            st.rerun()

# --- TAB 2: 管理 ---
with tabs[2]:
    if st.button("🔥 清空并重置所有蜂群数据"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute()
        st.success("蜂巢已清空")
        st.rerun()