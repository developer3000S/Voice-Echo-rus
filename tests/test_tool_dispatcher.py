"""Тесты восстановленного диспетчера инструментов.

Проверяют, что после миграции с облачного AI на локальную модель:
1. main.py распознаёт поручения, требующие выполнения инструментами;
2. связка planner -> executor -> task_queue доходит до реальных модулей actions/*;
3. «висячая» ветвь cmd_control (модуль никогда не существовал в проекте)
   безопасно маршрутизируется вместо ImportError.
"""
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import agent.planner as planner  # noqa: E402
import agent.executor as executor  # noqa: E402
from main import _looks_like_tool_request  # noqa: E402


def _stub_plan(steps):
    """Подменяет LLM-вызов планёра на детерминированный план (без обращения к Ollama)."""
    payload = json.dumps({"goal": "test", "steps": steps})
    planner.llm.chat = lambda prompt, system="", max_tokens=4096, temperature=0.3: payload


def test_looks_like_tool_request_detects_commands():
    assert _looks_like_tool_request("открой блокнот")
    assert _looks_like_tool_request("создай презентацию о космосе")
    assert _looks_like_tool_request("find the latest news")
    assert _looks_like_tool_request("напомни о встрече")


def test_looks_like_tool_request_ignores_chitchat():
    assert not _looks_like_tool_request("привет")
    assert not _looks_like_tool_request("кто ты?")
    assert not _looks_like_tool_request("объясни, как работает RAG")
    assert not _looks_like_tool_request("")


def test_main_dispatches_tool_requests():
    """main.py направляет поручения на стек выполнения, а не в фолбэк-ответчик."""
    main_text = (ROOT_DIR / "main.py").read_text(encoding="utf-8")
    assert "_run_tool_task" in main_text
    assert "_looks_like_tool_request(text)" in main_text
    assert "from agent.task_queue import get_queue" in main_text


def test_planner_parses_plan_without_name_error():
    """re.sub больше не роняет планёр NameError'ом (regression: отсутствовало import re)."""
    _stub_plan([
        {"step": 1, "tool": "open_app", "description": "open notepad",
         "parameters": {"app_name": "notepad"}, "critical": True},
    ])
    plan = planner.create_plan("открой блокнот")
    assert plan["steps"][0]["tool"] == "open_app"


def test_executor_dispatches_to_action_modules():
    """Шаги плана доходят до диспетчера _call_tool с корректными именами инструментов."""
    _stub_plan([
        {"step": 1, "tool": "open_app", "description": "open notepad",
         "parameters": {"app_name": "notepad"}, "critical": True},
        {"step": 2, "tool": "cmd_control", "description": "open file",
         "parameters": {"task": "открой блокнот"}, "critical": True},
        {"step": 3, "tool": "office_builder", "description": "deck",
         "parameters": {"kind": "presentation", "title": "Космос"}, "critical": True},
    ])

    calls = []
    real_call_tool = executor._call_tool

    def _recording_call(tool, parameters, speak):
        calls.append(tool)
        return f"{tool}-stub"

    executor._call_tool = _recording_call
    try:
        executor.AgentExecutor().execute("открой блокнот и сделай презентацию", speak=None)
    finally:
        executor._call_tool = real_call_tool

    assert calls == ["open_app", "cmd_control", "office_builder"]


def test_cmd_control_branch_does_not_raise_import_error():
    """«Висячая» ветвь cmd_control безопасно маршрутизируется на open_app,
    а не падает с ImportError (actions/cmd_control.py никогда не существовал)."""
    result = executor._call_tool(
        "cmd_control", {"task": "открой блокнот"}, speak=None
    )
    assert isinstance(result, str)
    assert "блокнот" in result
