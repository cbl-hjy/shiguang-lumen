# -*- coding: utf-8 -*-
"""OpenTelemetry 配置（2026-08-27 P1-6，pydantic-ai OTel-native 集成）。

背景：pydantic-ai 每次 run 自动发射标准 OTel spans（模型调用/tool/延迟/token），
只需设置全局 TracerProvider 即生效——自建 trace（observability.py）语义不标准，此为补强。

设计决策（数据本地化铁律）：**不接 Logfire 云**（官方推荐但数据会上传）——纯本地
ConsoleSpanExporter，控制台可看每次 agent 调用的 span 树；后续需要持久化再换 file exporter。
"""
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

_configured = False


def init_telemetry() -> None:
    """启动时调用一次：全局 TracerProvider + 开启 pydantic-ai 埋点（幂等）。
    机制（读 pydantic-ai 2.27 源码确认）：Agent.instrument_all(True) 全局开启——
    比 logfire.instrument_pydantic_ai() 更底层，不依赖 Logfire 云（数据本地化铁律）。"""
    global _configured
    if _configured:
        return
    _configured = True
    provider = TracerProvider(resource=Resource.create({"service.name": "shiguang"}))
    # Simple 同步导出（本地开发可接受；量大会有 IO 开销——需生产化时换 BatchSpanProcessor）
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    try:
        from pydantic_ai import Agent

        Agent.instrument_all(True)  # 全局开启（对后续创建的 agent 生效）
    except Exception as _e:
        print(f"[app/telemetry] 静默异常已可见化: {_e}", flush=True)
