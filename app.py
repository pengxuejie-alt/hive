with tabs[2]:
    st.subheader("⚙️ 蜂巢核心管理")
    
    # --- 1. 系统自检 ---
    if st.button("🔍 执行系统自检"):
        with st.status("正在检查核心链路...", expanded=True) as status:
            st.write("检查 Polygon API 连接...")
            # 这里的 clients 是我们在 init_hive_engine 中初始化的
            test_p = clients['poly'].get_snapshot_ticker("stocks", "GLD")
            st.write("检查 Gemini 决策中枢...")
            test_g = clients['gen_client'].models.list_models()
            st.write("检查 Supabase 数据库...")
            test_s = clients['supabase'].table("drones").select("count", count="exact").execute()
            status.update(label="✅ 系统链路畅通", state="complete")
        st.success(f"当前蜂巢活跃工蜂总数: {test_s.count}")

    st.divider()

    # --- 2. 危险操作区 ---
    st.warning("⚠️ 危险操作区：以下操作不可撤销")
    
    # 使用二级确认机制，防止误点
    if "confirm_delete" not in st.session_state:
        st.session_state.confirm_delete = False

    if not st.session_state.confirm_delete:
        if st.button("🗑️ 清空所有工蜂数据", type="secondary"):
            st.session_state.confirm_delete = True
            st.rerun()
    else:
        st.error("确定要抹除所有工蜂的灵魂吗？这将清空所有持仓、资金和日志。")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔥 确认毁灭", type="primary"):
                # 🚨 执行清空逻辑
                clients['supabase'].table("drones").delete().neq("name", "RESERVED_SYSTEM_DRONE").execute()
                st.session_state.confirm_delete = False
                st.success("蜂巢已重置为初始状态。")
                st.rerun()
        with c2:
            if st.button("❌ 取消"):
                st.session_state.confirm_delete = False
                st.rerun()