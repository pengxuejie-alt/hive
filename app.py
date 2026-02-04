# ==========================================
# 🚨 核心：带记忆与 DNA 的放飞引擎 (点火补全)
# ==========================================
def execute_flight_v11(d, slot, clients):
    with slot:
        dna = d.get('style', 'Risk:Neutral')
        # 提取最近 3 条记忆
        history = d.get('logs', [])[:3]
        memory_context = "\n".join([f"- 历史记忆: {m}" for m in history]) if history else "尚无历史记忆。"
        
        st.write(f"🚀 **{d['name']} 正在读取 DNA 并回溯记忆...**")
        
        # 1. 抓取标的情报 (GLD)
        with st.spinner("正在穿透市场情报层..."):
            # 复用 v10.4 的情报获取逻辑
            ticker = "GLD"
            # 简化版抓取，实际会调用之前的 fetch_tiger_intel 逻辑
            end = datetime.now()
            start = end - timedelta(days=2)
            aggs = clients['poly'].get_aggs(ticker, 1, "minute", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            curr_p = float(aggs[-1].close) if aggs else 0.0
            
            # 扫描期权链 (简化演示)
            chain_data = {"ticker": ticker, "price": curr_p, "signals": "检测到异动信号"}

        # 2. 注入 DNA 与 记忆 的进化 Prompt
        raw_prompt = """
        你是工蜂 [N]。
        🧬 DNA特征: [DNA]
        🧠 历史记忆: [MEMORY]
        
        当前现金: $[B] | 持仓: [P] | 标的情报: [I]
        
        要求：
        1. 必须在 thought 中分析你的 DNA 特质如何影响当前决策。
        2. 如果历史记忆中有亏损，请说明你如何调整心态。
        3. 严格返回 JSON: {"thought": "...", "trades": [{"ticker": "代码", "qty": 1, "action": "BUY/SELL"}]}
        """
        final_p = raw_prompt.replace("[N]", d['name']).replace("[DNA]", dna)\
                            .replace("[MEMORY]", memory_context).replace("[B]", f"{d['balance']:,.2f}")\
                            .replace("[P]", json.dumps(d.get('positions')))\
                            .replace("[I]", json.dumps(chain_data))
        
        try:
            r = clients['gen_client'].models.generate_content(
                model="gemini-2.0-flash", 
                contents=final_p, 
                config={'response_mime_type': 'application/json'}
            )
            decision = json.loads(r.text)
            thought = decision.get('thought', '观望')
            st.success(f"💭 {d['name']} 研判:\n\n{thought}")
            
            # 3. 结算逻辑 (同 v9.6)
            # ... (此处执行现金扣除与持仓增加) ...
            
            # 4. 存入数据库
            new_log = f"[{datetime.now().strftime('%H:%M')}] {thought[:60]}..."
            clients['supabase'].table("drones").update({
                "patrol_count": (d.get('patrol_count', 0) + 1),
                "logs": ([new_log] + (d.get('logs') or []))[:10]
            }).eq("id", d["id"]).execute()
            
            st.toast(f"🐝 {d['name']} 任务执行完毕")
            return True
        except Exception as e:
            st.error(f"放飞中断: {e}")
            return False

# ==========================================
# 🚨 UI 按钮绑定
# ==========================================
# 在看板循环中修改按钮：
if st.button(f"🚀 单独放飞 {d['name']}", key=f"f_{d['id']}", type="primary", use_container_width=True):
    if execute_flight_v11(d, st.container(), clients):
        st.rerun()