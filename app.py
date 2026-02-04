import streamlit as st
import re
import json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai
from polygon import RESTClient

# --- 1. 配置 ---
VERSION = "v4.6 (Error Fix)"
ACTIVE_BRAIN = "gemini-2.0-flash"

def get_config(key): return os.environ.get(key) or st.secrets.get(key)

try:
    S_URL, S_KEY = get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")
    G_KEY, P_KEY = get_config("GEMINI_KEY"), get_config("POLYGON_KEY")
    supabase = create_client(S_URL, S_KEY)
    gen_client = genai.Client(api_key=G_KEY)
    poly_client = RESTClient(api_key=P_KEY)
except Exception as e:
    st.error(f"❌ 初始化失败: {e}"); st.stop()

# --- 2. 数量识别工具 (解决你说的读不到数量问题) ---
def extract_count(text):
    # 匹配 "3只", "3 只", "三只" 等
    num_map = {'一':1, '二':2, '三':3, '四':4, '五':5, '六':6, '七':7, '八':8, '九':9, '十':10}
    
    # 先试阿拉伯数字
    match = re.search(r'(\d+)\s*只', text)
    if match: return int(match.group(1))
    
    # 再试中文数字
    for cn, num in num_map.items():
        if f"{cn}只" in text: return num
    
    return None # 没读到

# --- 3. 神经调度 ---
def safe_brain_decision(prompt):
    try:
        r = gen_client.models.generate_content(model=ACTIVE_BRAIN, contents=prompt, config={'response_mime_type': 'application/json'})
        data = json.loads(r.text)
        return data[0] if isinstance(data, list) else data
    except Exception as e:
        st.error(f"🧠 神经中枢响应异常: {e}")
        return None

# --- 4. UI 布局 ---
st.set_page_config(page_title="Hive 调试版", layout="wide")

h1, h2 = st.columns([4, 1])
h1.title(f"🐝 Hive 蜂群生态系统 `{VERSION}`")
if h2.button("🔄 刷新档案"): st.rerun()

# 强制重读数据
d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res:
        st.info("档案库空。")
    else:
        for d in d_res:
            with st.expander(f"🐝 {d['name']} | 资产: ${d['total_assets']:,.2f}"):
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"🧬 **基因:** {d.get('persona')}")
                    st.write(f"🧠 **记忆:** {d.get('memory')}")
                with c2:
                    st.write("**📦 持仓:**")
                    st.json(d.get('positions', {}))
                for l in (d.get('logs') or [])[:3]: st.caption(l)

with tabs[1]:
    st.subheader("👑 蜂后集群孵化")
    instr = st.text_area("指令 (例如：孵化3只GLD工蜂):", value="孵化3只GLD工蜂")
    
    if st.button("🔥 执行集群孵化"):
        # 💡 这里是解决问题的核心
        try:
            final_count = extract_count(instr)
            
            if final_count is None:
                st.warning("⚠️ 没从文案里读到明确数量（如'3只'），默认孵化 1 只。")
                final_count = 1
            
            if final_count > 10:
                st.error("🚫 数量过多（上限10只），请重新输入。")
                st.stop()

            with st.spinner(f"🧬 正在并行合成 {final_count} 只工蜂..."):
                def spawn(idx):
                    p = f"设计JSON：{{'name':'3字中文名','logic':'','persona':'','portfolio':['GLD']}}。内容中文。指令：{instr}。扰动：{idx}-{time.time()}"
                    item = safe_brain_decision(p)
                    if item:
                        uid = f"{random.randint(100,999)}"
                        item.update({
                            "name": f"{item.get('name', '工蜂')}-{uid}",
                            "balance": 100000.0, "total_assets": 100000.0,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "logs": ["诞生于 v4.6"], "positions": {}, "fly_count": 0, "memory": "初始"
                        })
                        supabase.table("drones").insert(item).execute()
                        return item['name']
                    return None

                with ThreadPoolExecutor(max_workers=final_count) as exe:
                    names = list(exe.map(spawn, range(final_count)))
                
                success_list = [n for n in names if n]
                st.success(f"✅ 成功入库: {', '.join(success_list)}")
                time.sleep(2)
                st.rerun()

        except Exception as e:
            # 💡 固化报错：不再一闪而过，而是直接钉在页面上
            st.error("🚨 孵化流程发生致命错误！")
            st.exception(e) # 这会显示完整的 Traceback

with tabs[2]:
    if st.button("🔥 清空"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute()
        st.rerun()