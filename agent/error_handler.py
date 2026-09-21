import json
import re
import sys
from pathlib import Path
from enum import Enum

from llm_client import client as llm


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()


class ErrorDecision(Enum):
    RETRY       = "retry"      
    SKIP        = "skip"       
    REPLAN      = "replan"     
    ABORT       = "abort"    


ERROR_ANALYST_PROMPT = """Ты — модель восстановления ошибок ИИ-ассистента Voice Echo.

Шаг задачи завершился ошибкой. Проанализируй ошибку и реши, что делать.

РЕШЕНИЯ:
- retry   : Временная ошибка (таймаут сети, временная блокировка файла, состояние гонки).
             Тот же шаг может успешно выполниться при повторе.
- skip    : Этот шаг не критичен, и задача может быть выполнена без него.
- replan  : Подход был ошибочным. Следует попробовать другой инструмент или метод.
- abort   : Задача фундаментально невыполнима или небезопасна для продолжения.

Также укажи:
- Краткое объяснение, ПОЧЕМУ произошла ошибка (1 предложение)
- Предложение исправления, если решение replan (что попробовать вместо этого)
- Максимум повторов: сколько раз повторить при решении retry (1 или 2)

Верни ТОЛЬКО валидный JSON:
{
  "decision": "retry|skip|replan|abort",
  "reason": "почему произошла ошибка",
  "fix_suggestion": "что попробовать вместо этого (для replan)",
  "max_retries": 1,
  "user_message": "Короткое сообщение для пользователя (максимум 15 слов)"
}
"""

def analyze_error(
    step: dict,
    error: str,
    attempt: int = 1,
    max_attempts: int = 2
) -> dict:
    """
    Analyzes a failed step and returns a recovery decision.

    Args:
        step         : The step dict that failed
        error        : Error message/traceback
        attempt      : Current attempt number
        max_attempts : How many times we've already tried

    Returns:
        {
            "decision": ErrorDecision,
            "reason": str,
            "fix_suggestion": str,
            "max_retries": int,
            "user_message": str
        }
    """
    if attempt >= max_attempts:
        print(f"[ErrorHandler] ⚠️ Max attempts reached for step {step.get('step')} — forcing replan")
        return {
            "decision":      ErrorDecision.REPLAN,
            "reason":        f"Failed {attempt} times: {error[:100]}",
            "fix_suggestion": "Try a completely different approach or tool",
            "max_retries":   0,
            "user_message":  "Пробую другой подход."
        }

    prompt = f"""Проваленный шаг:
Инструмент: {step.get('tool')}
Описание: {step.get('description')}
Параметры: {json.dumps(step.get('parameters', {}), indent=2)}
Критичный: {step.get('critical', False)}

Ошибка:
{error[:500]}

Номер попытки: {attempt}"""

    try:
        text = llm.chat(
            prompt,
            system=ERROR_ANALYST_PROMPT.strip(),
            max_tokens=1024,
            temperature=0.2,
        )
        text     = text.strip()
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

        result = json.loads(text)
        decision_str = result.get("decision", "replan").lower()
        decision_map = {
            "retry":  ErrorDecision.RETRY,
            "skip":   ErrorDecision.SKIP,
            "replan": ErrorDecision.REPLAN,
            "abort":  ErrorDecision.ABORT,
        }
        result["decision"] = decision_map.get(decision_str, ErrorDecision.REPLAN)


        if step.get("critical") and result["decision"] == ErrorDecision.SKIP:
            result["decision"]     = ErrorDecision.REPLAN
            result["user_message"] = "Этот шаг критичен — ищу альтернативный подход."

        print(f"[ErrorHandler] Decision: {result['decision'].value} — {result.get('reason', '')}")
        return result

    except Exception as e:
        print(f"[ErrorHandler] ⚠️ Analysis failed: {e} — defaulting to replan")
        return {
            "decision":       ErrorDecision.REPLAN,
            "reason":         str(e),
            "fix_suggestion": "Try alternative approach",
            "max_retries":    1,
            "user_message":   "Возникла проблема, меняю подход."
        }


def generate_fix(step: dict, error: str, fix_suggestion: str) -> dict:
    """
    When decision is REPLAN and a fix suggestion exists,
    generates a replacement step using generated_code as fallback.

    Returns a modified step dict.
    """
    prompt = f"""Шаг задачи завершился ошибкой. Сгенерируй шаг-замену.

Исходный шаг:
Инструмент: {step.get('tool')}
Описание: {step.get('description')}
Параметры: {json.dumps(step.get('parameters', {}), indent=2)}

Ошибка: {error[:300]}
Предложение исправления: {fix_suggestion}

Напиши Python-скрипт, который достигает той же цели другим путём.
Верни ТОЛЬКО Python-код, без пояснений."""

    try:
        code = llm.chat(
            prompt,
            system="Ты — экспертный Python-разработчик. Верни ТОЛЬКО Python-код, без пояснений, без markdown.",
            max_tokens=4096,
            temperature=0.2,
        )
        code = code.strip()
        code = re.sub(r"```(?:python)?", "", code).strip().rstrip("`").strip()

        return {
            "step":        step.get("step"),
            "tool":        "claude_code",
            "description": f"Auto-fix for: {step.get('description')}",
            "parameters": {
                "description": fix_suggestion,
            },
            "depends_on": step.get("depends_on", []),
            "critical":   step.get("critical", False)
        }

    except Exception as e:
        print(f"[ErrorHandler] ⚠️ Fix generation failed: {e}")
        return {
            "step":        step.get("step"),
            "tool":        "generated_code",
            "description": f"Fallback for: {step.get('description')}",
            "parameters":  {"description": step.get("description", "")},
            "depends_on":  step.get("depends_on", []),
            "critical":    step.get("critical", False)
        }