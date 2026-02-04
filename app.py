with tabs[1]:
    st.subheader("👑 蜂后大规模孵化 (v3.7 强化版)")
    col_l, col_r = st.columns([3, 1])
    with col_l:
        instr = st.text_area("孵化指令:", value="孵化3只德州之神工蜂，每只都要有独特的性格")
    with col_r:
        batch_count = st.number_input("数量", min_value=1, max_value=10, value=3)
    
    if st.button("🔥 启动集群孵化"):
        if not instr:
            st.warning("请输入指令")
        else:
            with st.spinner(f"🧬 正在并发合成 {batch_count} 个生命特征..."):
                def spawn_one(idx):
                    # 💡 关键修复：加入 idx 和随机数，强制 Gemini 生成不同的内容
                    seed = random.randint(1000, 9999)
                    p = f"""
                    设计一个工蜂JSON：{{'name':'','logic':'','persona':'','portfolio':['GLD']}}。
                    要求：中文描述，性格独特。
                    指令：{instr}
                    唯一性指纹：#{idx}-{seed}
                    """
                    try:
                        # 错开请求时间，避免 API 瞬时 Burst
                        time.sleep(idx * 0.3) 
                        item = safe_brain_decision(p)
                        if item:
                            # 💡 强制修正名字，防止数据库因重名“合并”
                            original_name = item.get('name', '匿名工蜂')
                            item['name'] = f"{original_name} (S-{idx}-{seed})"
                            
                            item.update({
                                "balance": 100000.0, "total_assets": 100000.0, 
                                "created_at": datetime.now(timezone.utc).isoformat(), 
                                "logs": [f"于集群任务 #{idx} 中诞生"], 
                                "positions": {}
                            })
                            supabase.table("drones").insert(item).execute()
                            return item['name']
                    except Exception as e:
                        return f"Error: {str(e)}"
                    return None

                with ThreadPoolExecutor(max_workers=batch_count) as executor:
                    names = list(executor.map(spawn_one, range(batch_count)))
                
                success_list = [n for n in names if n and "Error" not in n]
                st.success(f"✅ 成功孵化 {len(success_list)} 只工蜂: {', '.join(success_list)}")
                if len(success_list) < batch_count:
                    st.error(f"⚠️ 有 {batch_count - len(success_list)} 只工蜂在合成中折损。")
                
                time.sleep(1.5)
                st.rerun()