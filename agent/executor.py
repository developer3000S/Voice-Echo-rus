import json
import re
import sys
import threading
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Callable

from agent.planner       import create_plan, replan
from agent.error_handler import analyze_error, generate_fix, ErrorDecision
from llm_client          import client as llm


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()


def _run_generated_code(description: str, speak: Callable | None = None) -> str:
    if speak:
        speak("Пишу собственный код для этой задачи.")

    home      = Path.home()
    desktop   = home / "Desktop"
    downloads = home / "Downloads"
    documents = home / "Documents"

    if not desktop.exists():
        try:
            import winreg
            key     = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
            desktop = Path(winreg.QueryValueEx(key, "Desktop")[0])
        except Exception:
            pass

    client = llm
    system_instruction = (
        "You are an expert Python developer. "
        "Write clean, complete, working Python code. "
        "Use standard library + common packages. "
        "Install missing packages with subprocess + pip if needed. "
        "Return ONLY the Python code. No explanation, no markdown, no backticks.\n\n"
        f"SYSTEM PATHS:\n"
        f"  Desktop   = r'{desktop}'\n"
        f"  Downloads = r'{downloads}'\n"
        f"  Documents = r'{documents}'\n"
        f"  Home      = r'{home}'\n"
    )

    try:
        code = client.chat(
            f"Write Python code to accomplish this task:\n\n{description}",
            system=system_instruction,
            max_tokens=4096,
            temperature=0.2,
        )
        code = code.strip()
        code = re.sub(r"```(?:python)?", "", code).strip().rstrip("`").strip()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        print(f"[Executor] 🐍 Running generated code: {tmp_path}")

        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True,
            timeout=120, cwd=str(Path.home())
        )

        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        output = result.stdout.strip()
        error  = result.stderr.strip()

        if result.returncode == 0 and output:
            return output
        elif result.returncode == 0:
            return "Задача успешно выполнена."
        elif error:
            raise RuntimeError(f"Code error: {error[:400]}")
        return "Выполнено."

    except subprocess.TimeoutExpired:
        raise RuntimeError("Generated code timed out after 120 seconds.")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Generated code failed: {e}")

def _inject_context(params: dict, tool: str, step_results: dict, goal: str = "") -> dict:
    if not step_results:
        return params

    params = dict(params)

    if tool == "file_controller" and params.get("action") in ("write", "create_file"):
        content = params.get("content", "")
        if not content or len(content) < 50:
            all_results = [
                v for v in step_results.values()
                if v and len(v) > 100 and v not in ("Готово.", "Выполнено.")
            ]
            if all_results:
                combined = "\n\n---\n\n".join(all_results)
                translated = _translate_to_goal_language(combined, goal)
                params["content"] = translated
                print(f"[Executor] 💉 Injected + translated content")

    return params
def _detect_language(text: str) -> str:
    try:
        return llm.chat(
            "What language is this text written in? "
            "Reply with ONLY the language name in English (e.g. Turkish, English, French).\n\n"
            f"Text: {text[:200]}",
            system="Reply with ONLY the language name in English.",
            max_tokens=20,
            temperature=0.0,
        ).strip()
    except Exception:
        return "English"


def _translate_to_goal_language(content: str, goal: str) -> str:
    if not goal:
        return content
    try:
        target_lang = _detect_language(goal)
        print(f"[Executor] 🌐 Translating to: {target_lang}")

        prompt = (
            f"You are a professional translator. "
            f"Translate the following text into {target_lang}.\n"
            f"IMPORTANT:\n"
            f"- Translate EVERYTHING, leave nothing in English\n"
            f"- Keep all facts, numbers, and data intact\n"
            f"- Keep the structure and formatting\n"
            f"- Output ONLY the translated text, nothing else\n\n"
            f"Text to translate:\n{content[:4000]}"
        )
        translated = llm.chat(
            prompt,
            system="You are a professional translator. Output ONLY the translated text.",
            max_tokens=4096,
            temperature=0.3,
        ).strip()
        print(f"[Executor] ✅ Translation done ({target_lang})")
        return translated
    except Exception as e:
        print(f"[Executor] ⚠️ Translation failed: {e}")
        return content

def _call_tool(tool: str, parameters: dict, speak: Callable | None) -> str:

    if tool == "open_app":
        from actions.open_app import open_app
        return open_app(parameters=parameters, player=None) or "Готово."

    elif tool == "web_search":
        from actions.web_search import web_search
        return web_search(parameters=parameters, player=None) or "Готово."
    elif tool == "game_updater":
        from actions.game_updater import game_updater
        return game_updater(parameters=parameters, player=None, speak=speak) or "Готово."
    elif tool == "browser_control":
        from actions.browser_control import browser_control
        return browser_control(parameters=parameters, player=None) or "Готово."

    elif tool == "file_controller":
        from actions.file_controller import file_controller
        return file_controller(parameters=parameters, player=None) or "Готово."

    elif tool == "cmd_control":
        from actions.cmd_control import cmd_control
        return cmd_control(parameters=parameters, player=None) or "Готово."

    elif tool == "claude_code":
        from actions.claude_code_bridge import run_developer_mode_request
        claude_parameters = dict(parameters or {})
        claude_parameters.setdefault("workspace_path", str(Path.cwd()))
        return run_developer_mode_request(claude_parameters, speak=speak)

    elif tool == "screen_process":
        from actions.screen_processor import screen_process
        screen_process(parameters=parameters, player=None)
        return "Скриншот сделан и проанализирован."

    elif tool == "send_message":
        from actions.send_message import send_message
        return send_message(parameters=parameters, player=None) or "Готово."

    elif tool == "reminder":
        from actions.reminder import reminder
        return reminder(parameters=parameters, player=None) or "Готово."

    elif tool == "youtube_video":
        from actions.youtube_video import youtube_video
        return youtube_video(parameters=parameters, player=None) or "Готово."

    elif tool == "weather_report":
        from actions.weather_report import weather_action
        return weather_action(parameters=parameters, player=None) or "Готово."

    elif tool == "computer_settings":
        from actions.computer_settings import computer_settings
        return computer_settings(parameters=parameters, player=None) or "Готово."

    elif tool == "desktop_control":
        from actions.desktop import desktop_control
        return desktop_control(parameters=parameters, player=None) or "Готово."

    elif tool == "computer_control":
        from actions.computer_control import computer_control
        return computer_control(parameters=parameters, player=None) or "Готово."

    elif tool == "generated_code":
        description = parameters.get("description", "")
        if not description:
            raise ValueError("Для generated_code требуется параметр 'description'.")
        from actions.claude_code_bridge import run_developer_mode_request
        return run_developer_mode_request(
            {"description": description, "workspace_path": str(Path.cwd())},
            speak=speak,
        )

    elif tool == "flight_finder":
        from actions.flight_finder import flight_finder
        return flight_finder(parameters=parameters, player=None, speak=speak) or "Готово."

    elif tool in ("spotify_controller", "spotify", "music"):
        from actions.spotify_controller import spotify_controller
        return spotify_controller(parameters=parameters, player=None, speak=speak) or "Готово."

    elif tool in ("calendar_scheduler", "calendar", "schedule"):
        from actions.calendar_scheduler import calendar_scheduler
        return calendar_scheduler(parameters=parameters, player=None, speak=speak) or "Готово."

    elif tool in ("daily_briefing", "briefing"):
        from actions.daily_briefing import daily_briefing
        return daily_briefing(parameters=parameters, player=None, speak=speak) or "Готово."

    elif tool in ("code_helper", "code_agent"):
        from actions.code_helper import code_helper
        return code_helper(parameters=parameters, player=None, speak=speak) or "Готово."

    elif tool == "calorie_counter":
        from actions.calorie_counter import run as run_calorie_counter
        return run_calorie_counter(parameters=parameters, player=None) or "Готово."

    elif tool == "pushup_counter":
        from actions.pushup_counter import run as run_pushup_counter
        return run_pushup_counter(parameters=parameters, player=None) or "Готово."

    elif tool == "system_monitor":
        from actions.system_monitor import run as run_system_monitor
        return run_system_monitor(parameters=parameters, player=None) or "Готово."

    elif tool == "upload_video":
        from actions.upload_video import run as run_upload_video
        return run_upload_video(parameters=parameters, player=None) or "Готово."
    else:
        print(f"[Executor] ⚠️ Unknown tool '{tool}' — no developer fallback is configured")
        return f"Неизвестное действие: {tool}"

class AgentExecutor:

    MAX_REPLAN_ATTEMPTS = 2

    def execute(
        self,
        goal:        str,
        speak:       Callable | None        = None,
        cancel_flag: threading.Event | None = None,
    ) -> str:
        print(f"\n[Executor] 🎯 Goal: {goal}")

        replan_attempts = 0
        completed_steps = []
        step_results    = {} 
        plan            = create_plan(goal)

        while True:
            steps = plan.get("steps", [])

            if not steps:
                msg = "Не удалось создать корректный план для этой задачи."
                if speak: speak(msg)
                return msg

            success      = True
            failed_step  = None
            failed_error = ""

            for step in steps:
                if cancel_flag and cancel_flag.is_set():
                    if speak: speak("Задача отменена.")
                    return "Задача отменена."

                step_num = step.get("step", "?")
                tool     = step.get("tool", "generated_code")
                desc     = step.get("description", "")
                params   = step.get("parameters", {})

                params = _inject_context(params, tool, step_results, goal=goal)

                print(f"\n[Executor] ▶️ Step {step_num}: [{tool}] {desc}")

                attempt = 1
                step_ok = False

                while attempt <= 3:
                    if cancel_flag and cancel_flag.is_set():
                        break
                    try:
                        result = _call_tool(tool, params, speak)
                        step_results[step_num] = result 
                        completed_steps.append(step)
                        print(f"[Executor] ✅ Step {step_num} done: {str(result)[:100]}")
                        step_ok = True
                        break

                    except Exception as e:
                        error_msg = str(e)
                        print(f"[Executor] ❌ Step {step_num} attempt {attempt} failed: {error_msg}")

                        recovery = analyze_error(step, error_msg, attempt=attempt)
                        decision = recovery["decision"]
                        user_msg = recovery.get("user_message", "")

                        if speak and user_msg:
                            speak(user_msg)

                        if decision == ErrorDecision.RETRY:
                            attempt += 1
                            import time; time.sleep(2)
                            continue

                        elif decision == ErrorDecision.SKIP:
                            print(f"[Executor] ⏭️ Skipping step {step_num}")
                            completed_steps.append(step)
                            step_ok = True
                            break

                        elif decision == ErrorDecision.ABORT:
                            msg = f"Задача прервана. {recovery.get('reason', '')}"
                            if speak: speak(msg)
                            return msg

                        else: 
                            fix_suggestion = recovery.get("fix_suggestion", "")
                            if fix_suggestion and tool != "generated_code":
                                try:
                                    fixed_step = generate_fix(step, error_msg, fix_suggestion)
                                    if speak: speak("Пробую альтернативный подход.")
                                    res = _call_tool(
                                        fixed_step["tool"],
                                        fixed_step["parameters"],
                                        speak
                                    )
                                    step_results[step_num] = res
                                    completed_steps.append(step)
                                    step_ok = True
                                    break
                                except Exception as fix_err:
                                    print(f"[Executor] ⚠️ Fix failed: {fix_err}")

                            failed_step  = step
                            failed_error = error_msg
                            success      = False
                            break

                if not step_ok and not failed_step:
                    failed_step  = step
                    failed_error = "Max retries exceeded"
                    success      = False

                if not success:
                    break

            if success:
                return self._summarize(goal, completed_steps, speak)

            if replan_attempts >= self.MAX_REPLAN_ATTEMPTS:
                msg = f"Задача не выполнена после {replan_attempts} попыток перепланирования."
                if speak: speak(msg)
                return msg

            if speak: speak("Корректирую свой подход.")

            replan_attempts += 1
            plan = replan(goal, completed_steps, failed_step, failed_error)

    def _summarize(self, goal: str, completed_steps: list, speak: Callable | None) -> str:
        fallback = f"Готово. Выполнено шагов: {len(completed_steps)}. Задача: {goal[:60]}."
        try:
            steps_str = "\n".join(f"- {s.get('description', '')}" for s in completed_steps)
            prompt    = (
                f'Цель пользователя: "{goal}"\n'
                f"Выполненные шаги:\n{steps_str}\n\n"
                "Напиши одно естественное предложение, резюмирующее, что было выполнено. "
                "Обращайся к пользователю на «ты». Будь кратким и позитивным."
            )
            summary = llm.chat(
                prompt,
                system="Напиши одно краткое естественное предложение-резюме на русском.",
                max_tokens=256,
                temperature=0.5,
            ).strip()
            if speak: speak(summary)
            return summary
        except Exception:
            if speak: speak(fallback)
            return fallback
