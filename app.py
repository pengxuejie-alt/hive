import streamlit as st
import re
from supabase import create_client
import json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from google import genai
from polygon import RESTClient

# --- 1. 配置与初始化 ---
VERSION = "v4.5 (Deep Debug)"
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

# --- 2. 核心诊断与刷新函数 ---
def force_refresh_data():
    """强制清理所有缓存并重读数据库"""
    st.cache_data.clear()
    return supabase.table("drones").select("*").order("created_at", desc=True).execute().data

# --- 3. 神经调度引擎 ---
def safe_brain_decision(prompt):
    for attempt in range(3):
        try:
            time.sleep(0.3)
            r = gen_client.models.generate_content(model=ACTIVE_BRAIN, contents=prompt, config={'response_mime_type': 'application/json'})
            data = json.loads(r.text)
            return data[0] if isinstance(data, list) else data
        except Exception as e:
            if "429" in str(e): time.sleep(2); continue
            raise e

# --- 4. 演化逻辑 ---
def execute_worker_cycle(d, slot):
    with slot:
        try:
            st.write("📡 **多源行情采集...**")
            targets = d.get('portfolio', ['SPY', 'GLD'])
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(lambda t: {"代码": t, "现价": random.uniform(150, 200)}, targets)) # 调试占位
            nectar_data = {r['代码']: r for r in results}
            
            st.info(f"📊 行情透传: {json.dumps(nectar_data)}")
            prompt = f"你是工蜂{d['name']}。基因:{d['persona']}。现金:{d['balance']}。行情:{json.dumps(nectar_data)}。返回决策JSON。"
            decision = safe_brain_decision(prompt)

            # 更新数据库
            supabase.table("drones").update({
                "fly_count": (d.get('fly_count', 0) + 1),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] 放飞成功"] + (d.get('logs') or []))[:10]
            }).eq("id", d["id"]).execute()
            st.success("✅ 数据已存入")
            time.sleep(1)
            st.rerun()
        except Exception as e:
            st.error(f"❌ 运行失败: {e}")

# --- 5. UI 界面 ---
st.set_page_config(page_title="Hive 调试版", layout="wide")

# 侧边栏调试台
with st.sidebar:
    st.subheader("🛠️ 系统诊断台")
    if st.button("🔄 强制重载数据库"):
        st.rerun()
    st.caption(f"版本: {VERSION}")

h1, h2 = st.columns([4, 1])
h1.title(f"🐝 Hive 蜂群生态系统")
full_fly = h2.button("🔥 全量放飞", type="primary", use_container_width=True)

d_res = force_refresh_data()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res:
        st.info("⚠️ 档案库暂无数据。")
    else:
        for d in d_res:
            header = f"🐝 {d['name']} | 资产: ${d['total_assets']:,.2f} | 基因: {d.get('persona','')[:15]}..."
            with st.expander(header):
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"🧬 **基因:** {d.get('persona')}")
                    st.write(f"🧠 **记忆:** {d.get('memory')}")
                with c2:
                    st.write("**📦 持仓:**")
                    st.json(d.get('positions', {}))
                
                if st.button(f"🚀 单独放飞", key=f"b_{d['id']}"):
                    execute_worker_cycle(d, st.container())

with tabs[1]:
    st.subheader("👑 蜂后集群孵化")
    instr = st.text_area("指令:", value="孵化3只GLD工蜂")
    
    if st.button("🔥 执行孵化"):
        match = re.search(r'(\d+)只', instr)
        final_count = int(match.group(1)) if match else 1
        
        with st.spinner(f"🧬 正在合成 {final_count} 只工蜂..."):
            def spawn(idx):
                p = f"设计JSON：{{'name':'3字中文名','logic':'','persona':'','portfolio':['GLD']}}。内容中文。指令：{instr}"
                try:
                    item = safe_brain_decision(p)
                    # 💡 增加绝对唯一的随机后缀，防止数据库因重名静默失败
                    uid = f"{random.randint(100,999)}-{idx}"
                    item.update({
                        "name": f"{item.get('name', '工蜂')}-{uid}",
                        "balance": 100000.0, "total_assets": 100000.0,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "logs": ["诞生"], "positions": {}, "fly_count": 0, "memory": "初始"
                    })
                    # 💡 调试日志
                    res = supabase.table("drones").insert(item).execute()
                    return item['name']
                except Exception as e:
                    return f"Error: {e}"

            with ThreadPoolExecutor(max_workers=final_count) as exe:
                names = list(exe.map(spawn, range(final_count)))
            
            st.success(f"✅ 完成: {', '.join(filter(None, names))}")
            time.sleep(2)
            st.rerun()

with tabs[2]:
    if st.button("🔥 清空"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute()
        st.rerun()