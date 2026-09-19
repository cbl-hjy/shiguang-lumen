"""A1 后台沉淀钩子（Phase 4 A-2，2026-08-29：从 chat.py 纯移动拆分）。

职责：会话 done 后异步执行 6 路沉淀（profile/confusion/relation/continuation/teaching/topics）。
设计（2026-08-20）：done 立即发出（体验：不等数十秒提炼）；提炼后台跑（成本：不阻塞响应）。
glint 留在流内（SSE glint 事件需 done 前推前端挂金光点）。
全局串行锁：防并发写 memory 文件竞态（relation/continuation 同写 state.json）+ 防 DeepSeek 429 堆积。
"""

import asyncio

from app import observability as obs

# 全局串行锁：防并发写 memory 文件竞态（relation/continuation 同写 state.json）+ 防 DeepSeek 429 堆积。
_POST_HOOK_LOCK = asyncio.Semaphore(1)
_POST_HOOK_TASKS: set = set()  # 持有引用防 GC（可观测：模块级可查）


# ---------- A1 后台沉淀钩子（2026-08-20）----------
# 设计：6 路纯沉淀钩子（profile/confusion/relation/continuation/teaching/topics）done 后异步跑——
# done 立即发出（体验：不等数十秒提炼）；提炼后台跑（成本：不阻塞响应）。
# glint 留在流内（SSE glint 事件需 done 前推前端挂金光点）。
# 全局串行锁：防并发写 memory 文件竞态（relation/continuation 同写 state.json）+ 防 DeepSeek 429 堆积。
_POST_HOOK_LOCK = asyncio.Semaphore(1)
_POST_HOOK_TASKS: set = set()  # 持有引用防 GC（可观测：模块级可查）


async def _run_post_hooks(
    sid: str, run_id: str, dialogue: str, need_profile: bool, tool_fails: int = 0, uid: str | None = None
) -> None:
    """done 后异步执行的收尾沉淀（A1，2026-08-20）。
    与流内 glint 分工：glint 需 SSE 推送留流内；其余纯沉淀全后台。"""
    async with _POST_HOOK_LOCK:
        # profile（记忆变化门——consume 已提前到流内，这里只执行）
        if need_profile:
            try:
                from app.memory.store import update_profile

                rp = await update_profile()
                obs.hook(run_id, "profile", True, rp)
                print(f"[profile] 会话 {sid[:8]} 记忆变化 → {rp}", flush=True)
            except Exception as e3:
                try:
                    from app.memory.store import log_change

                    log_change("extractor_failed", "profile 画像刷新失败")
                except Exception as _e:
                    print(f"[routers/chat] 静默异常已可见化: {_e}", flush=True)
                obs.hook(run_id, "profile", False, str(e3))
                obs.error(run_id, "hook_profile", str(e3))
                print(f"[profile] 会话 {sid[:8]} 画像刷新失败: {e3}", flush=True)
        if not dialogue:
            return
        # 困惑（P0-2 方案B：每会话末必跑——"聊了困惑但没 remember"是最该提炼的场景）
        try:
            from app.agent.tutor import build_tutor_agent

            build_tutor_agent(uid)  # 确保提炼回调已注册（主对话已调过，这里兜底）
            from app.memory.store import extract_session_confusion, remember

            confusion = await extract_session_confusion(dialogue)
            if confusion:
                r = await remember(confusion, source="agent", importance=7, category="困惑")
                obs.hook(run_id, "confusion", True, r)
                print(f"[confusion] 会话 {sid[:8]} 提炼困惑 → {r}", flush=True)
        except Exception as e4:
            try:
                from app.memory.store import log_change

                log_change("extractor_failed", "confusion 提炼失败")
            except Exception as _e:
                print(f"[routers/chat] 静默异常已可见化: {_e}", flush=True)
            obs.hook(run_id, "confusion", False, str(e4))
            obs.error(run_id, "hook_confusion", str(e4))
            print(f"[confusion] 会话 {sid[:8]} 困惑提炼失败: {e4}", flush=True)
        # 关系轨（阶段1）：提炼"我们之间"→ 写 state.json（慢变状态）
        try:
            from app.memory.store import extract_session_relation
            from app.memory.state import update_relation

            rel = await extract_session_relation(dialogue)
            if rel:
                rr = update_relation(
                    depth=rel.get("depth", ""),
                    last_topic=rel.get("last_topic", ""),
                    tone=rel.get("tone", ""),
                    evidence=dialogue[:120],
                )
                obs.hook(run_id, "relation", True, rr)
                print(f"[relation] 会话 {sid[:8]} 关系轨 → {rr}", flush=True)
        except Exception as e5:
            try:
                from app.memory.store import log_change

                log_change("extractor_failed", "relation 提炼失败")
            except Exception as _e:
                print(f"[routers/chat] 静默异常已可见化: {_e}", flush=True)
            obs.hook(run_id, "relation", False, str(e5))
            obs.error(run_id, "hook_relation", str(e5))
            print(f"[relation] 会话 {sid[:8]} 关系轨提炼失败: {e5}", flush=True)
        # 任务轨续接点（阶段2）：提炼"下次从哪继续"→ 写 state.json
        try:
            from app.memory.store import extract_session_continuation
            from app.memory.state import update_continuation

            cont = await extract_session_continuation(dialogue)
            if cont:
                cr = update_continuation(next_step=cont, evidence=dialogue[:120])
                obs.hook(run_id, "continuation", True, cr)
                print(f"[continuation] 会话 {sid[:8]} 续接点 → {cr}", flush=True)
        except Exception as e6:
            try:
                from app.memory.store import log_change

                log_change("extractor_failed", "continuation 提炼失败")
            except Exception as _e:
                print(f"[routers/chat] 静默异常已可见化: {_e}", flush=True)
            obs.hook(run_id, "continuation", False, str(e6))
            obs.error(run_id, "hook_continuation", str(e6))
            print(f"[continuation] 会话 {sid[:8]} 续接点提炼失败: {e6}", flush=True)
        # 教学经验（自主反思）：反思/技能不再"等用户喂"（机器触发，判断归模型）
        try:
            from app.memory.store import extract_session_teaching
            from app.agent.evolution import reflect_teaching, save_skill

            # P1-3（2026-08-27）：失败信号提升反思优先级——有工具失败时，教学提炼器
            # 看到失败上下文会优先产出反思/技能修订（双统计量"难度"信号的轻量代理）
            _teach_in = dialogue
            if tool_fails > 0:
                _teach_in = (
                    f"{dialogue}\n\n（本轮有 {tool_fails} 次工具执行失败——"
                    f"若与教学/工具使用方式有关，请优先反思并给出改进）"
                )
            teaching = await extract_session_teaching(_teach_in)
            if teaching:
                if teaching.get("reflection"):
                    rr_ = await reflect_teaching(f"会话复盘：{teaching['reflection']}")
                    obs.hook(run_id, "teaching", True, f"反思 {rr_}")
                    print(f"[teaching] 会话 {sid[:8]} 反思 → {rr_}", flush=True)
                if teaching.get("skill_method"):
                    sk_ = await save_skill(
                        description=teaching.get("skill_desc") or teaching.get("skill_method")[:60],
                        method=teaching["skill_method"],
                    )
                    obs.hook(run_id, "teaching", True, f"技能 {sk_}")
                    print(f"[teaching] 会话 {sid[:8]} 技能 → {sk_}", flush=True)
        except Exception as e7:
            try:
                from app.memory.store import log_change

                log_change("extractor_failed", "teaching 提炼失败")
            except Exception as _e:
                print(f"[routers/chat] 静默异常已可见化: {_e}", flush=True)
            obs.hook(run_id, "teaching", False, str(e7))
            obs.error(run_id, "hook_teaching", str(e7))
            print(f"[teaching] 会话 {sid[:8]} 教学经验提炼失败: {e7}", flush=True)
        # ACE playbook（第七路，2026-08-30）：Reflector 提炼 delta → Curator 确定性合并（零 LLM）。
        # bump 接地校验集由代码侧计算（session_grounded_sids）——模型提的无接地 bump 一律丢弃。
        try:
            from app.agent import evolution as _evo
            from app.memory.store import extract_session_playbook

            entries = await extract_session_playbook(dialogue)
            if entries:
                rp_ = await _evo.apply_delta(entries, grounded=_evo.session_grounded_sids(sid))
                obs.hook(run_id, "playbook", True, rp_)
                print(f"[playbook] 会话 {sid[:8]} delta → {rp_}", flush=True)
        except Exception as e9:
            try:
                from app.memory.store import log_change

                log_change("extractor_failed", "playbook 提炼失败")
            except Exception as _e:
                print(f"[routers/chat] 静默异常已可见化: {_e}", flush=True)
            obs.hook(run_id, "playbook", False, str(e9))
            obs.error(run_id, "hook_playbook", str(e9))
            print(f"[playbook] 会话 {sid[:8]} playbook 提炼失败: {e9}", flush=True)
        finally:
            # 会话注册表清理（检索/verify/显式反馈）——无论提炼成败都执行
            try:
                from app.agent import evolution as _evo2

                _evo2.end_session(sid)
                # 成熟度门控事件点（2026-08-30 设计 §3-2）：会话收尾扫 deprecated 且
                # 连续 ≥14 天无新 helpful 的技能 → 出向量索引（文件保留可找回，事件驱动非批量任务）
                _evo2.exit_deprecated_skills()
            except Exception as _e:
                print(f"[routers/chat] 静默异常已可见化: {_e}", flush=True)
        # 跨域类比（第八路，2026-08-31，路线图 v3.0 §4「差异化心脏」）：
        # cadence ≥7 天 + evidence 锚定校验归 analogy 模块（不变量锁死代码）；判断归模型。
        # 绝不注入对话——只落 analogies.jsonl，进「它记得我」抽屉由用户自己点开。
        try:
            from app.agent import analogy as _ana
            from app.memory.store import extract_session_analogy

            rec = await extract_session_analogy(dialogue)
            if rec:
                ra_ = _ana.append_analogy(rec)
                obs.hook(run_id, "analogy", True, ra_)
                print(f"[analogy] 会话 {sid[:8]} 跨域类比 → {ra_}", flush=True)
        except Exception as e10:
            try:
                from app.memory.store import log_change

                log_change("extractor_failed", "analogy 提炼失败")
            except Exception as _e:
                print(f"[routers/chat] 静默异常已可见化: {_e}", flush=True)
            obs.hook(run_id, "analogy", False, str(e10))
            obs.error(run_id, "hook_analogy", str(e10))
            print(f"[analogy] 会话 {sid[:8]} 类比提炼失败: {e10}", flush=True)
        # 主题提炼（意图驱动）：模型识别主题+归并，harness 只做意图分流 + 确定性验证
        try:
            from app.memory.store import extract_session_topics
            from app.memory.topics_store import (
                find_topic,
                mark_farewell,
                register_candidate,
                set_status,
                touch_topic,
            )

            tps = await extract_session_topics(dialogue)
            _topic_events = 0
            if tps and tps.get("topics"):
                for tp in tps["topics"]:
                    # 2026-08-20 trace 抓出：模型输出可能含非 dict 元素 → harness 过滤
                    if not isinstance(tp, dict):
                        continue
                    name, intent, _conf = tp["name"], tp["intent"], tp.get("confidence", "high")
                    if intent == "learning":
                        if find_topic(name):
                            touch_topic(name)
                            print(f"[topics] 会话 {sid[:8]} learning → {name}", flush=True)
                        else:
                            r = register_candidate(name)
                            print(
                                f"[topics] 会话 {sid[:8]} learning未命中→候选 {name} count={r.get('count')} created={r.get('created')}",
                                flush=True,
                            )
                    elif intent == "new":
                        r = register_candidate(name)
                        print(
                            f"[topics] 会话 {sid[:8]} new → {name} count={r.get('count')} created={r.get('created')}",
                            flush=True,
                        )
                    elif intent == "farewell":
                        if mark_farewell(name):
                            print(f"[topics] 会话 {sid[:8]} farewell → {name}", flush=True)
                    # 状态落盘（2026-08-21 状态细粒度归模型）：模型输出的 status 优先于关键词规则
                    status = str(tp.get("status", "") or "").strip().lower()
                    if status in ("done", "stuck", "shelved"):
                        if set_status(name, status):
                            print(f"[topics] 会话 {sid[:8]} {name} status→{status}", flush=True)
                    # mention → 完全不动（提到≠想学，防误激活，体验关键）
                    _topic_events += 1
            # 2026-08-21 修复：hook 移到 if 外——"无主题"也是结果（曾因 hook 在 if 内 → 提炼静默死 2 天零记录）
            obs.hook(run_id, "topics", True, f"{_topic_events} 个主题事件")
        except Exception as e8:
            import traceback

            traceback.print_exc()  # 错误详情落 stderr（配合 trace 定位）
            try:
                from app.memory.store import log_change

                log_change("extractor_failed", "topics 提炼失败")
            except Exception as _e:
                print(f"[routers/chat] 静默异常已可见化: {_e}", flush=True)
            obs.hook(run_id, "topics", False, str(e8))
            obs.error(run_id, "hook_topics", str(e8))
            print(f"[topics] 会话 {sid[:8]} 主题提炼失败: {e8}", flush=True)


