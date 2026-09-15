# actions/reminder.py

import os
import sys
import subprocess
import threading
import time
from datetime import datetime


def _notify(message: str) -> None:
    """Best-effort desktop notification, cross-platform."""
    try:
        if os.name == "nt":
            try:
                from win10toast import ToastNotifier
                ToastNotifier().show_toast("MARK Reminder", message, duration=15, threaded=True)
                return
            except Exception:
                pass
            try:
                import winsound
                for freq in (800, 1000, 1200):
                    winsound.Beep(freq, 200)
                    time.sleep(0.1)
                return
            except Exception:
                pass
        elif sys.platform == "darwin":
            subprocess.run(
                ["osascript", "-e", f'display notification "{message}" with title "MARK Reminder"'],
                check=False, timeout=5,
            )
            return
        else:
            for cmd in (
                ["notify-send", "MARK Reminder", message],
                ["zenity", "--info", "--text", f"MARK Reminder\n{message}"],
            ):
                try:
                    subprocess.run(cmd, check=False, timeout=5)
                    return
                except (FileNotFoundError, subprocess.SubprocessError):
                    continue
    except Exception:
        pass


def _notify_in_thread(message: str) -> None:
    threading.Thread(target=_notify, args=(message,), daemon=True).start()


def reminder(
    parameters: dict,
    response: str | None = None,
    player=None,
    session_memory=None
) -> str:
    """
    Sets a timed reminder.

    parameters:
        - date    (str) YYYY-MM-DD
        - time    (str) HH:MM
        - message (str)

    On Windows uses the Task Scheduler; on macOS/Linux uses a background
    thread (cross-platform, no admin required). Returns a result string.
    """

    date_str = parameters.get("date")
    time_str = parameters.get("time")
    message  = parameters.get("message", "Reminder")

    if not date_str or not time_str:
        return "I need both a date and a time to set a reminder."

    try:
        target_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")

        if target_dt <= datetime.now():
            return "That time is already in the past."

        safe_message = message.replace('"', '').replace("'", "").strip()[:200]
        human_time = target_dt.strftime('%B %d at %I:%M %p')

        if os.name == "nt":
            return _schedule_windows_task(target_dt, safe_message, human_time, player)
        return _schedule_threaded(target_dt, safe_message, human_time, player)

    except ValueError:
        return "I couldn't understand that date or time format."

    except Exception as e:
        return f"Something went wrong while scheduling the reminder: {str(e)[:80]}"


def _schedule_threaded(target_dt, safe_message, human_time, player) -> str:
    def _runner():
        delay = (target_dt - datetime.now()).total_seconds()
        if delay > 0:
            time.sleep(delay)
        _notify_in_thread(safe_message)

    threading.Thread(target=_runner, daemon=True, name=f"Reminder-{target_dt:%Y%m%d_%H%M}").start()

    if player:
        player.write_log(f"[reminder] set for {human_time}")

    return f"Reminder set for {human_time}."


def _schedule_windows_task(target_dt, safe_message, human_time, player) -> str:
    task_name    = f"MARKReminder_{target_dt.strftime('%Y%m%d_%H%M')}"

    python_exe = sys.executable
    if python_exe.lower().endswith("python.exe"):
        pythonw = python_exe.replace("python.exe", "pythonw.exe")
        if os.path.exists(pythonw):
            python_exe = pythonw

    temp_dir      = os.environ.get("TEMP", "C:\\Temp")
    notify_script = os.path.join(temp_dir, f"{task_name}.pyw")
    project_root  = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    script_code = f'''import sys, os, time
sys.path.insert(0, r"{project_root}")

try:
    import winsound
    for freq in [800, 1000, 1200]:
        winsound.Beep(freq, 200)
        time.sleep(0.1)
except Exception:
    pass

try:
    from win10toast import ToastNotifier
    ToastNotifier().show_toast(
        "MARK Reminder",
        "{safe_message}",
        duration=15,
        threaded=False
    )
except Exception:
    try:
        import subprocess
        subprocess.run(["msg", "*", "/TIME:30", "{safe_message}"], shell=True)
    except Exception:
        pass

time.sleep(3)
try:
    os.remove(__file__)
except Exception:
    pass
'''
    with open(notify_script, "w", encoding="utf-8") as f:
        f.write(script_code)

    xml_content = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>MARK Reminder: {safe_message}</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>{target_dt.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>{python_exe}</Command>
      <Arguments>"{notify_script}"</Arguments>
    </Exec>
  </Actions>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Principals>
    <Principal>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
</Task>'''

    xml_path = os.path.join(temp_dir, f"{task_name}.xml")
    with open(xml_path, "w", encoding="utf-16") as f:
        f.write(xml_content)

    result = subprocess.run(
        f'schtasks /Create /TN "{task_name}" /XML "{xml_path}" /F',
        shell=True, capture_output=True, text=True
    )

    try:
        os.remove(xml_path)
    except Exception:
        pass

    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip()
        print(f"[Reminder] ❌ schtasks failed: {err}")
        try:
            os.remove(notify_script)
        except Exception:
            pass
        return "I couldn't schedule the reminder due to a system error."

    if player:
        player.write_log(f"[reminder] set for {human_time}")

    return f"Reminder set for {human_time}."