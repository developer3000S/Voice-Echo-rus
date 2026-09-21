import os
import subprocess
import sys
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

from llm_client import client as llm


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
API_CONFIG_PATH  = BASE_DIR / "config" / "api_keys.json"
def _projects_dir() -> Path:
    desktop = Path.home() / "Desktop"
    if desktop.is_dir():
        return desktop / "JarvisProjects"
    return Path.home() / "Documents" / "JarvisProjects"


PROJECTS_DIR     = _projects_dir()
MAX_FIX_ATTEMPTS = 5

def _get_model(model_name: str = ""):
    class _W:
        def generate_content(self, contents):
            return SimpleNamespace(text=llm.chat(str(contents)))

    return _W()


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\r?\n?", "", text)
    text = re.sub(r"\r?\n?```\s*$", "", text)
    return text.strip()


def _is_rate_limit(error: Exception) -> bool:
    msg = str(error).lower()
    return "429" in msg or "quota" in msg or "resource_exhausted" in msg


def _parse_traceback(output: str, project_files: list[str]) -> tuple[str | None, int | None]:

    pattern = re.compile(r'File ["\']([^"\']+\.py)["\'],\s+line\s+(\d+)', re.IGNORECASE)
    matches = pattern.findall(output)

    for raw_path, line_str in reversed(matches):
        raw_name = Path(raw_path).name
        for pf in project_files:
            if Path(pf).name == raw_name or pf == raw_path or raw_path.endswith(pf):
                return pf, int(line_str)

    return None, None


def _classify_error(output: str) -> str:

    low = output.lower()

    if any(x in low for x in ("no module named", "modulenotfounderror", "importerror")):
        return "dependency_error"

    if "syntaxerror" in low or "invalid syntax" in low:
        return "syntax_error"
    
    if "cannot import" in low or "importerror" in low:
        return "import_error"

    if any(x in low for x in (
        "traceback", "exception", "error:", "nameerror", "typeerror",
        "attributeerror", "valueerror", "keyerror", "indexerror",
        "zerodivisionerror", "filenotfounderror", "permissionerror",
    )):
        return "runtime_error"

    return "none"


def _has_error(output: str, run_command: str) -> bool:
    
    low = output.lower()

    if "timed out" in low:
        return False

    if not output.strip():
        return False

    error_type = _classify_error(output)
    return error_type != "none"

class RateLimitError(Exception):
    pass


def _plan_project(description: str, language: str) -> dict:
    model = _get_model()

    prompt = f"""Ты — старший архитектор программного обеспечения. Создай минимальный, полный план файлов для этого проекта.

Язык: {language}
Описание: {description}

Верни ТОЛЬКО валидный JSON — без markdown, без пояснений:
{{
  "project_name": "snake_case_name",
  "entry_point": "main.py",
  "files": [
    {{
      "path": "main.py",
      "description": "Entry point — what it does and which modules it imports",
      "imports": ["utils.helpers", "core.engine"]
    }},
    {{
      "path": "utils/helpers.py",
      "description": "Helper utilities — what functions it exposes",
      "imports": []
    }}
  ],
  "run_command": "python main.py",
  "dependencies": ["requests"]
}}

Критические правила:
1. Перечисляй файлы В ПОРЯДКЕ ЗАВИСИМОСТЕЙ — файлы без импортов первыми, точка входа последней.
2. Поле "imports" должно содержать каждый модуль проекта, который импортирует этот файл (через точку, например "utils.helpers").
3. Держи план минимальным — только действительно нужные файлы.
4. Точка входа должна быть в списке файлов.
5. Используй только относительные пути (например "utils/helpers.py", не абсолютные).
6. Модули стандартной библиотеки (os, sys, json и т.д.) НЕ попадают в "dependencies".

JSON:"""

    try:
        response = model.generate_content(prompt)
        raw = _strip_fences(response.text)
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Planner returned invalid JSON: {e}\nRaw: {response.text[:300]}")
    except Exception as e:
        if _is_rate_limit(e):
            raise RateLimitError(str(e))
        raise

def _write_file(
    file_info: dict,
    project_description: str,
    all_files: list[dict],
    language: str,
    project_dir: Path,
    already_written: dict[str, str],
) -> str:
    model = _get_model()

    file_path = file_info["path"]
    file_desc = file_info.get("description", "")
    file_imports = file_info.get("imports", [])

    file_list = "\n".join(
        f"  [{i+1}] {f['path']}: {f.get('description', '')}"
        for i, f in enumerate(all_files)
    )

    dependency_context = ""
    for dep_dotted in file_imports:
        dep_path = dep_dotted.replace(".", "/") + ".py"
        if dep_path in already_written:
            code_snippet = already_written[dep_path][:2000]
            dependency_context += f"\n\n--- {dep_path} (you must import from this) ---\n{code_snippet}"

    lang_rules = ""
    if language.lower() == "python":
        lang_rules = """
Python-specific rules:
- Use type hints for all function signatures.
- Add docstrings for all public functions and classes.
- Use if __name__ == "__main__": guard in the entry point.
- For relative imports within the project, use: from utils.helpers import foo  (match the project structure exactly).
- Do NOT use implicit relative imports (from . import ...) unless it's a proper package with __init__.py.
- If this is a package subdirectory, create __init__.py files where needed."""
    elif language.lower() in ("javascript", "typescript", "js", "ts"):
        lang_rules = """
JS/TS-specific rules:
- Use ES modules (import/export), not CommonJS (require).
- Add JSDoc comments for all exported functions.
- Handle promise rejections with try/catch in async functions."""

    prompt = f"""Ты — старший {language}-разработчик, пишущий код производственного качества для реального проекта.

Цель проекта: {project_description}

Полная структура файлов проекта (в порядке зависимостей):
{file_list}

{f"Зависимости, которые этот файл должен импортировать из других файлов проекта:{dependency_context}" if dependency_context else ""}

Твоя задача: напиши полный, рабочий код для: {file_path}
Назначение этого файла: {file_desc}
{f"Этот файл импортирует из: {', '.join(file_imports)}" if file_imports else "У этого файла нет внутренних импортов из проекта."}

{lang_rules}

Общие правила:
- Выводи ТОЛЬКО чистый код. Абсолютно без пояснений, без markdown, без тройных обратных кавычек.
- Пиши ПОЛНЫЙ, ИСПОЛНЯЕМЫЙ код — без заглушек, без "# TODO", без пустых pass.
- Каждый импорт должен быть либо из стандартной библиотеки, либо из перечисленных зависимостей, либо из файлов проекта, показанных выше.
- Пути импорта должны ТОЧНО совпадать с путями файлов в структуре проекта (например, если файл "utils/helpers.py", импортируй как "from utils.helpers import ...").
- Используй правильную обработку ошибок (try/except) там, где есть I/O или сетевые вызовы.
- Код должен корректно работать при запуске точки входа проекта из корневой директории проекта.

Код для {file_path}:"""

    try:
        response = model.generate_content(prompt)
        code = _strip_fences(response.text)

        full_path = project_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(code, encoding="utf-8")

        print(f"[DevAgent] ✅ Written: {file_path} ({len(code)} chars)")
        return code

    except Exception as e:
        if _is_rate_limit(e):
            raise RateLimitError(str(e))
        raise

def _install_dependencies(dependencies: list[str], project_dir: Path) -> str:
    if not dependencies:
        return "No external dependencies."

    to_install = []
    for dep in dependencies:
        pkg_name = re.split(r"[>=<!]", dep)[0].strip()
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", pkg_name],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            to_install.append(dep)
        else:
            print(f"[DevAgent] ✓ Already installed: {pkg_name}")

    if not to_install:
        return f"All dependencies already installed: {', '.join(dependencies)}"

    print(f"[DevAgent] 📦 Installing: {to_install}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install"] + to_install,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=120, cwd=str(project_dir)
        )
        if result.returncode == 0:
            return f"Installed: {', '.join(to_install)}"
        return f"Install warning (non-fatal): {result.stderr[:200]}"
    except subprocess.TimeoutExpired:
        return "Dependency install timed out (non-fatal)."
    except Exception as e:
        return f"Install error (non-fatal): {e}"

def _open_vscode(project_dir: Path) -> bool:
    import shutil

    # Cross-platform VS Code candidates: try shutil.which first,
    # then fall back to known paths per OS.
    candidates: list[str] = ["code"]

    if os.name == "nt":
        candidates += [
            rf"C:\Users\{Path.home().name}\AppData\Local\Programs\Microsoft VS Code\bin\code.cmd",
            r"C:\Program Files\Microsoft VS Code\bin\code.cmd",
            r"C:\Program Files (x86)\Microsoft VS Code\bin\code.cmd",
        ]
    elif sys.platform == "darwin":
        candidates += [
            r"/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
        ]

    executable = shutil.which(candidates[0]) if shutil.which else None
    if not executable:
        # Fall back to Path.exists() for absolute paths in the list
        for c in candidates:
            path = Path(c)
            if path.exists():
                executable = str(path)
                break

    if not executable:
        return False

    # Use shell=True only for .cmd/.bat executables
    use_shell = executable.lower().endswith((".cmd", ".bat"))

    try:
        subprocess.Popen(
            [executable, str(project_dir)],
            shell=use_shell,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(1.5)
        print(f"[DevAgent] 💻 VSCode opened: {project_dir}")
        return True
    except Exception:
        return False

def _run_project(run_command: str, project_dir: Path, timeout: int = 30) -> str:
    print(f"[DevAgent] 🚀 Running: {run_command}")
    try:
        parts = run_command.split()
        if parts[0].lower() == "python":
            parts[0] = sys.executable

        result = subprocess.run(
            parts,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout,
            cwd=str(project_dir)
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        combined_parts = []
        if stdout:
            combined_parts.append(f"STDOUT:\n{stdout}")
        if stderr:
            combined_parts.append(f"STDERR:\n{stderr}")

        return "\n\n".join(combined_parts) if combined_parts else "Ran with no output."

    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s — long-running app (server/GUI) is likely working."
    except FileNotFoundError as e:
        return f"Command not found: {e}"
    except Exception as e:
        return f"Run error: {e}"

def _try_auto_install(error_output: str, project_dir: Path) -> bool:
    """ModuleNotFoundError varsa eksik paketi otomatik kurmaya çalışır."""
    pattern = re.compile(
        r"No module named ['\"]([a-zA-Z0-9_\-\.]+)['\"]", re.IGNORECASE
    )
    match = pattern.search(error_output)
    if not match:
        return False

    pkg = match.group(1).replace("_", "-").split(".")[0]
    print(f"[DevAgent] 🔧 Auto-installing missing package: {pkg}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=60, cwd=str(project_dir)
        )
        return result.returncode == 0
    except Exception:
        return False

def _fix_files(
    error_output: str,
    project_description: str,
    all_files: list[dict],
    file_codes: dict[str, str],
    language: str,
    project_dir: Path,
    entry_point: str,
) -> dict[str, str]:

    model = _get_model()

    error_file, error_line = _parse_traceback(error_output, list(file_codes.keys()))
    error_type = _classify_error(error_output)

    files_to_fix: list[str] = []

    if error_file:
        files_to_fix.append(error_file)
        if error_type == "import_error":
            for fi in all_files:
                if error_file.replace("/", ".").replace(".py", "") in fi.get("imports", []):
                    p = fi["path"]
                    if p not in files_to_fix:
                        files_to_fix.append(p)
    else:
        files_to_fix.append(entry_point)

    updated_codes: dict[str, str] = {}

    for fix_path in files_to_fix:
        current_code = file_codes.get(fix_path, "")

        other_ctx = ""
        for fp, code in file_codes.items():
            if fp != fix_path and code:
                snippet = code[:1500] + ("..." if len(code) > 1500 else "")
                other_ctx += f"\n--- {fp} ---\n{snippet}\n"

        line_hint = f"\nError appears to be near line {error_line} in this file." if (
            error_line and fix_path == error_file
        ) else ""

        prompt = f"""Ты — экспертный {language}-отладчик. Исправь сломанный файл ниже.

Цель проекта: {project_description}

Все файлы проекта:
{chr(10).join(f"  - {f['path']}: {f.get('description', '')}" for f in all_files)}

Другие файлы для контекста (только для чтения — исправляй только целевой файл):
{other_ctx[:3500]}

Файл для исправления: {fix_path}{line_hint}
Тип ошибки: {error_type}

Вывод ошибки:
{error_output[:2500]}

Текущий (сломанный) код:
{current_code}

Правила:
- Выводи ТОЛЬКО полный исправленный код. Без пояснений, без markdown, без обратных кавычек.
- Исправь ВСЕ ошибки, видимые в выводе ошибки.
- Сохрани всю существующую корректную логику — не удаляй рабочие функции.
- Пути импорта должны точно соответствовать реальной структуре файлов проекта.
- НЕ добавляй новые баги и не удаляй обработку ошибок.

Исправленный код для {fix_path}:"""

        try:
            response = model.generate_content(prompt)
            fixed = _strip_fences(response.text)

            full_path = project_dir / fix_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(fixed, encoding="utf-8")

            updated_codes[fix_path] = fixed
            print(f"[DevAgent] 🔧 Fixed: {fix_path}")

        except Exception as e:
            if _is_rate_limit(e):
                raise RateLimitError(str(e))
            print(f"[DevAgent] ⚠️ Could not fix {fix_path}: {e}")

    return updated_codes

def _build_project(
    description: str,
    language: str,
    project_name: str,
    timeout: int,
    speak=None,
    player=None,
) -> str:

    def log(msg: str):
        print(f"[DevAgent] {msg}")
        if player:
            player.write_log(f"[DevAgent] {msg}")

    log("Planning project structure...")
    try:
        plan = _plan_project(description, language)
    except RateLimitError:
        msg = "Rate limit reached, sir. Please try again in a moment."
        if speak: speak(msg)
        return msg
    except ValueError as e:
        msg = f"Planning failed: {e}"
        if speak: speak(msg)
        return msg

    proj_name    = project_name or plan.get("project_name", "jarvis_project")
    proj_name    = re.sub(r"[^\w\-]", "_", proj_name)
    project_dir  = PROJECTS_DIR / proj_name
    project_dir.mkdir(parents=True, exist_ok=True)

    files        = plan.get("files", [])
    entry_point  = plan.get("entry_point", "main.py")
    run_command  = plan.get("run_command", f"python {entry_point}")
    dependencies = plan.get("dependencies", [])

    log(f"Project: {proj_name} | Files: {len(files)} | Entry: {entry_point}")

    def _dep_sort_key(fi: dict) -> int:
        return len(fi.get("imports", []))

    sorted_files = sorted(files, key=_dep_sort_key)

    file_codes: dict[str, str] = {}

    for file_info in sorted_files:
        file_path = file_info.get("path", "")
        if not file_path:
            continue

        log(f"Writing {file_path}...")
        for attempt in range(2):
            try:
                code = _write_file(
                    file_info=file_info,
                    project_description=description,
                    all_files=files,
                    language=language,
                    project_dir=project_dir,
                    already_written=file_codes,
                )
                file_codes[file_path] = code
                time.sleep(0.4)
                break
            except RateLimitError:
                if attempt == 0:
                    log("Rate limit — waiting 20s...")
                    time.sleep(20)
                else:
                    log(f"Rate limit retry failed for {file_path}, skipping.")
            except Exception as e:
                log(f"Failed to write {file_path}: {e}")
                break

    if not file_codes:
        msg = "I could not write any project files, sir."
        if speak: speak(msg)
        return msg

    if dependencies:
        install_result = _install_dependencies(dependencies, project_dir)
        log(install_result)

    _open_vscode(project_dir)

    last_output   = ""
    auto_installs = 0  

    for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
        log(f"Running project (attempt {attempt}/{MAX_FIX_ATTEMPTS})...")
        last_output = _run_project(run_command, project_dir, timeout)
        log(f"Output preview: {last_output[:150]}")

        if not _has_error(last_output, run_command):
            msg = (
                f"Project '{proj_name}' is working, sir. "
                f"Built in {attempt} attempt{'s' if attempt > 1 else ''}. "
                f"Saved to: {project_dir}"
            )
            if speak: speak(msg)
            return f"{msg}\n\nOutput:\n{last_output}"

        if attempt == MAX_FIX_ATTEMPTS:
            break

        error_type = _classify_error(last_output)
        if error_type == "dependency_error" and auto_installs < 3:
            installed = _try_auto_install(last_output, project_dir)
            if installed:
                auto_installs += 1
                log("Missing dependency installed, retrying...")
                time.sleep(1)
                continue

        log(f"Fixing errors (type: {error_type})...")
        try:
            updated = _fix_files(
                error_output=last_output,
                project_description=description,
                all_files=files,
                file_codes=file_codes,
                language=language,
                project_dir=project_dir,
                entry_point=entry_point,
            )
            file_codes.update(updated)
            time.sleep(1)
        except RateLimitError:
            msg = "Rate limit reached during fix. Project saved, check it manually in VSCode."
            if speak: speak(msg)
            return msg
        except Exception as e:
            log(f"Fix step failed: {e}")

    msg = (
        f"I couldn't fully fix '{proj_name}' after {MAX_FIX_ATTEMPTS} attempts, sir. "
        f"Project is saved at {project_dir} — open it in VSCode and check manually."
    )
    if speak: speak(msg)
    return f"{msg}\n\nLast error:\n{last_output[:600]}"


def dev_agent(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    p            = parameters or {}
    description  = p.get("description", "").strip()
    language     = p.get("language", "python").strip()
    project_name = p.get("project_name", "").strip()
    timeout      = int(p.get("timeout", 30))

    if not description:
        return "Please describe the project you want me to build, sir."

    return _build_project(
        description  = description,
        language     = language,
        project_name = project_name,
        timeout      = timeout,
        speak        = speak,
        player       = player,
    )