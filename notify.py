"""
Desktop notification for the daily runner.

Scheduled tasks run in a non-interactive session where WinRT toasts are
unreliable, so this tries the toast first and falls back to msg.exe (which
reaches every session on Windows Server), then to plain stdout.

Never raises: a failed notification must not fail the pipeline.
"""
import os
import subprocess
import sys

_TOAST_PS = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$tpl = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
           [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$txt = $tpl.GetElementsByTagName('text')
$txt.Item(0).AppendChild($tpl.CreateTextNode($env:NOTIFY_TITLE)) | Out-Null
$txt.Item(1).AppendChild($tpl.CreateTextNode($env:NOTIFY_BODY))  | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($tpl)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Gas Short-Term').Show($toast)
"""


def notify(title: str, body: str) -> None:
    """Best-effort desktop notification; always echoes to stdout."""
    print(f"[notify] {title}: {body}", flush=True)
    if not sys.platform.startswith('win'):
        return

    env = dict(os.environ, NOTIFY_TITLE=title, NOTIFY_BODY=body)
    attempts = [
        (['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', _TOAST_PS], env),
        (['msg', '*', '/time:120', f'{title}: {body}'], None),
    ]
    for cmd, cmd_env in attempts:
        try:
            done = subprocess.run(cmd, env=cmd_env, capture_output=True, timeout=30)
            if done.returncode == 0:
                return
        except Exception:
            continue
