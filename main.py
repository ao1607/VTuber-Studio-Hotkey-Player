import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, cast
import os
import threading
import ctypes
import platform
import sys
import keyboard
import pygame
import pygetwindow as gw

import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox, scrolledtext
import zipfile
import tempfile
import shutil

Schedule = List[Tuple[float, str]]  # (秒, 押下するキー)
PausePoints = List[float]
PauseFlags = Dict[str, float]


def focus_window(title: str, wait_s: float = 0.3) -> None:
    # Try pygetwindow first, then fallback to enumerating windows via WinAPI
    try:
        windows = gw.getWindowsWithTitle(title)
    except Exception:
        windows = []

    hwnd = None
    if windows:
        window = windows[0]
        try:
            hwnd = int(window._hWnd)
        except Exception:
            hwnd = None

    if hwnd is None:
        # fallback: enumerate top-level windows and match title substring (case-insensitive)
        hwnd = _find_hwnd_by_title_substr(title)
        if hwnd is None:
            raise RuntimeError(f"ウィンドウが見つかりません: {title}")

    _bring_hwnd_to_front(hwnd)
    time.sleep(wait_s)


def _find_hwnd_by_title_substr(title_substr: str) -> Optional[int]:
    """Return the first HWND whose window text contains title_substr (case-insensitive), or None."""
    user32 = ctypes.windll.user32
    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    GetWindowTextLengthW = user32.GetWindowTextLengthW
    GetWindowTextW = user32.GetWindowTextW
    IsWindowVisible = user32.IsWindowVisible

    matches: List[int] = []

    def foreach(hwnd, lParam):
        try:
            if not IsWindowVisible(hwnd):
                return True
            length = GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            GetWindowTextW(hwnd, buf, length + 1)
            text = buf.value
            if title_substr.lower() in text.lower():
                matches.append(int(hwnd))
                return False  # stop enumeration
        except Exception:
            pass
        return True

    EnumWindows(EnumWindowsProc(foreach), 0)
    return matches[0] if matches else None


def _bring_hwnd_to_front(hwnd: int) -> None:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        time.sleep(0.05)

    fore_hwnd = user32.GetForegroundWindow()
    process_id = ctypes.c_ulong()
    fore_thread = user32.GetWindowThreadProcessId(fore_hwnd, ctypes.byref(process_id)) if fore_hwnd else 0
    current_thread = kernel32.GetCurrentThreadId()

    user32.ShowWindow(hwnd, 5)  # SW_SHOW
    if fore_thread and fore_thread != current_thread:
        user32.AttachThreadInput(fore_thread, current_thread, True)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(fore_thread, current_thread, False)
    else:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)

    # If still not foreground, try ALT key trick
    if user32.GetForegroundWindow() != hwnd:
        VK_MENU = 0x12
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, 2, 0)
        user32.SetForegroundWindow(hwnd)


def focus_vtube_studio(title_keyword: str = "VTube Studio", wait_s: float = 0.3, force_front: bool = True) -> None:
    """指定タイトルを含む VTube Studio ウィンドウをアクティブ化し、必要なら最前面へ一時的に押し出す。

    force_front=True の場合、一度 TOPMOST にしてから NOTOPMOST に戻すことで他アプリより前に確実に表示。
    これにより SetForegroundWindow が失敗するケース (ユーザ操作要件) を軽減。
    """
    matches = [t for t in gw.getAllTitles() if title_keyword.lower() in t.lower()]
    if not matches:
        raise RuntimeError("VTube Studioのウィンドウが見つかりません。起動とタイトルを確認してください。")
    focus_window(matches[0], wait_s)
    if not force_front:
        return
    try:
        hwnd = _find_hwnd_by_title_substr(title_keyword)
        if hwnd:
            user32 = ctypes.windll.user32
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_SHOWWINDOW = 0x0040
            # 一瞬 TOPMOST にして前面へ。すぐ通常状態へ戻す。
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            time.sleep(0.05)
            user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    except Exception:
        pass


def countdown(seconds: int = 3, message: str = "再生開始", log: Optional[Callable[[str], None]] = None) -> None:
    for remaining in range(seconds, 0, -1):
        text = f"{remaining}..."
        if log:
            log(text)
        else:
            print(text, flush=True)
        time.sleep(1)
    if log:
        log(message)
    else:
        print(message, flush=True)


def play_audio_with_hotkeys(
    audio_path: str,
    schedule: Schedule,
    hold_ms: int = 80,
    pause_points: Optional[PausePoints] = None,
    start_offset: float = 0.0,
    log_callback: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
    pause_control_add: Optional[Callable[[str, float, threading.Event], None]] = None,
    pause_control_remove: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> None:
    audio_file = Path(audio_path)
    if not audio_file.is_file():
        raise FileNotFoundError(f"音声ファイルが見つかりません: {audio_file}")

    def emit(message: str) -> None:
        print(message, flush=True)
        if log_callback:
            log_callback(message)

    sdl_version = ".".join(str(part) for part in pygame.get_sdl_version())
    emit(f"pygame {pygame.version.ver} (SDL {sdl_version}, Python {platform.python_version()})")
    emit(f"音声ファイル: {audio_file}")

    emit("VTube Studio のウィンドウにフォーカスします")
    focus_vtube_studio()
    emit("VTube Studio のウィンドウをアクティブ化しました")

    message = "再生開始" if start_offset == 0.0 else f"{start_offset:.3f}s から再生"
    countdown(message=message, log=emit)

    pygame.mixer.init()
    pygame.mixer.music.load(audio_file.as_posix())

    applied_offset = max(0.0, start_offset)
    pending = [(t, key) for t, key in schedule if t >= applied_offset]
    # Exclude pauses that are exactly at the start offset to avoid immediate pause
    eps = 1e-9
    pause_schedule = [t for t in (pause_points or []) if t > applied_offset + eps]

    try:
        if applied_offset > 0.0:
            pygame.mixer.music.play(start=applied_offset)
        else:
            pygame.mixer.music.play()
    except TypeError:
        pygame.mixer.music.play()
        if applied_offset > 0.0:
            try:
                pygame.mixer.music.set_pos(applied_offset)
            except pygame.error:
                emit("開始位置を設定できないため先頭から再生します。")
                applied_offset = 0.0
                pending = list(schedule)
                pause_schedule = list(pause_points or [])

    pending = sorted(pending, key=lambda pair: pair[0])
    pause_schedule = sorted(pause_schedule)
    fired: set[int] = set()
    pause_fired: set[int] = set()
    start = time.perf_counter() - applied_offset

    try:
        while pygame.mixer.music.get_busy():
            now = time.perf_counter() - start
            # report progress to caller (GUI) if provided
            if progress_callback is not None:
                try:
                    progress_callback(now)
                except Exception:
                    pass

            for idx, (target_sec, key) in enumerate(pending):
                if idx in fired:
                    continue
                if now >= target_sec:
                    emit(f"{now:.3f}s -> RShift+{key}")
                    keyboard.press("right shift")
                    keyboard.press(key)
                    time.sleep(hold_ms / 1000.0)
                    keyboard.release(key)
                    keyboard.release("right shift")
                    fired.add(idx)

            resumed_from_pause = False
            for idx, pause_sec in enumerate(pause_schedule):
                if idx in pause_fired:
                    continue
                if now >= pause_sec:
                    emit(f"{now:.3f}s -> 一時停止")
                    pygame.mixer.music.pause()
                    pause_started = time.perf_counter()
                    # report current time at pause moment
                    if progress_callback is not None:
                        try:
                            progress_callback(now)
                        except Exception:
                            pass
                    # Create a resume event and optionally expose a GUI control to trigger it
                    resume_event = threading.Event()

                    # If the caller provided a callback to add a pause control, call it
                    pause_id = f"pause-{idx}-{int(time.time()*1000)}"
                    if pause_control_add:
                        try:
                            pause_control_add(pause_id, pause_sec, resume_event)
                        except Exception:
                            pass

                    # Also allow Enter in console as a fallback to resume (only if a real console is attached)
                    def _wait_enter():
                        try:
                            # ブロッキング入力に成功した場合のみ再開
                            input()
                        except Exception:
                            return
                        try:
                            resume_event.set()
                        except Exception:
                            pass

                    try:
                        if sys.stdin is not None and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
                            threading.Thread(target=_wait_enter, daemon=True).start()
                    except Exception:
                        pass

                    # Wait until either Enter pressed (resume_event), stop requested, or GUI resume
                    while not resume_event.is_set():
                        if stop_event and stop_event.is_set():
                            emit("停止要求を受け取りました。再生を停止します。")
                            # notify GUI to remove control
                            if pause_control_remove:
                                try:
                                    pause_control_remove(pause_id)
                                except Exception:
                                    pass
                            pygame.mixer.music.stop()
                            return
                        time.sleep(0.1)
                    # resume_event is set -> remove GUI control
                    if pause_control_remove:
                        try:
                            pause_control_remove(pause_id)
                        except Exception:
                            pass
                    focus_vtube_studio()
                    countdown(message="再開", log=emit)
                    pause_duration = time.perf_counter() - pause_started
                    pygame.mixer.music.unpause()
                    start += pause_duration
                    pause_fired.add(idx)
                    resumed_from_pause = True
                    break

            if resumed_from_pause:
                continue

            time.sleep(0.005)
    finally:
        pygame.mixer.music.stop()
        pygame.mixer.quit()
        emit("再生を終了しました")


def load_timeline(path: str) -> Tuple[str, Schedule, PausePoints, PauseFlags]:
    path_obj = Path(path)
    data = json.loads(path_obj.read_text(encoding="utf-8"))
    audio_path = (path_obj.parent / data["audio_file"]).resolve()

    schedule: Schedule = []
    pauses: PausePoints = []
    flags: PauseFlags = {}

    for evt in data.get("events", []):
        schedule.append((float(evt["time"]), evt["key"]))
    pauses.extend(float(p) for p in data.get("pauses", []))

    for entry in data.get("timeline", []):
        t = float(entry["time"])
        kind = entry.get("type", "press")
        if kind == "press":
            schedule.append((t, entry["key"]))
        elif kind == "pause":
            pauses.append(t)
            flag = entry.get("flag")
            if flag is not None:
                flags[str(flag)] = t

    schedule = sorted(schedule, key=lambda pair: pair[0])
    pauses = sorted(pauses)
    return str(audio_path), schedule, pauses, flags


if __name__ == "__main__":
    class TimelineEditor(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(" VTube Studio ホットキー自動押下")
            self.geometry("820x520")

            self.audio_file_var = tk.StringVar()
            self.events: List[Dict] = []
            self.log_widget: Optional[scrolledtext.ScrolledText] = None
            self.progress: Optional[ttk.Progressbar] = None
            self.frm_progress: Optional[ttk.Frame] = None
            self._temp_audio_dirs: List[str] = []
            self.time_label: Optional[ttk.Label] = None
            # playback session management
            self._session_ctr: int = 0
            self._current_session: int = 0

            self.create_widgets()
            # ensure temp dirs cleaned up on close
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self.after(0, lambda: self.log("アプリケーションを起動しました"))

        def create_widgets(self):
            frm_top = ttk.Frame(self)
            frm_top.pack(fill="x", padx=8, pady=8)

            ttk.Label(frm_top, text="Audio:").pack(side="left")
            ttk.Entry(frm_top, textvariable=self.audio_file_var, width=60).pack(side="left", padx=6)
            ttk.Button(frm_top, text="音声ファイルを選択", command=self.browse_audio).pack(side="left")
            ttk.Button(frm_top, text="bundleを読み込み", command=self.load_bundle_file).pack(side="left", padx=6)
            ttk.Button(frm_top, text="名前をつけて保存(bundle)", command=self.save_bundle_file).pack(side="left")

            frm_mid = ttk.Frame(self)
            frm_mid.pack(fill="both", expand=True, padx=8, pady=(0,8))

            self.tree = ttk.Treeview(frm_mid, columns=("time", "type", "data"), show="headings", selectmode="browse")
            self.tree.heading("time", text="時間(秒)")
            self.tree.heading("type", text="種類")
            self.tree.heading("data", text="押下キー/フラグ番号")
            self.tree.column("time", width=120)
            self.tree.column("type", width=80)
            self.tree.column("data", width=120)
            self.tree.pack(side="left", fill="both", expand=True)

            vsb = ttk.Scrollbar(frm_mid, orient="vertical", command=self.tree.yview)
            vsb.pack(side="left", fill="y")
            self.tree.configure(yscrollcommand=vsb.set)

            frm_buttons = ttk.Frame(self)
            frm_buttons.pack(fill="x", padx=8, pady=8)

            ttk.Button(frm_buttons, text="押下キーを追加", command=self.add_press).pack(side="left")
            ttk.Button(frm_buttons, text="一時停止を追加", command=self.add_pause).pack(side="left", padx=6)
            ttk.Button(frm_buttons, text="編集", command=self.edit_event).pack(side="left")
            ttk.Button(frm_buttons, text="削除", command=self.delete_event).pack(side="left", padx=6)
            frm_run = ttk.Frame(self)
            frm_run.pack(fill="x", padx=8, pady=(0,8))
            ttk.Label(frm_run, text="開始フラグ: ").pack(side="left")
            self.start_flag_var = tk.StringVar()
            ttk.Entry(frm_run, textvariable=self.start_flag_var, width=8).pack(side="left")
            ttk.Button(frm_run, text="再生開始", command=self.start_playback).pack(side="left", padx=6)
            self.stop_button = ttk.Button(frm_run, text="停止", command=self.stop_playback)
            self.stop_button.pack(side="left", padx=6)
            self.stop_button.configure(state="disabled")

            self.status_var = tk.StringVar(value="Ready")
            # Status label on its own row, progress/time on the next row
            frm_status = ttk.Frame(self)
            frm_status.pack(fill="x", padx=8, pady=(0,2))
            ttk.Label(frm_status, textvariable=self.status_var).pack(side="left")

            self.frm_progress = ttk.Frame(self)
            self.frm_progress.pack(fill="x", padx=8, pady=(4,8))
            self._build_progress_controls()

            # pause controls frame (buttons to resume specific pauses)
            self.frm_pause_controls = ttk.Frame(self)
            self.frm_pause_controls.pack(fill="x", padx=8, pady=(0,4))

            frm_log = ttk.LabelFrame(self, text="ログ")
            frm_log.pack(fill="both", expand=False, padx=8, pady=(0,8))
            self.log_widget = scrolledtext.ScrolledText(frm_log, height=8, state="disabled", wrap="word")
            self.log_widget.pack(fill="both", expand=True)

        def browse_audio(self):
            p = filedialog.askopenfilename(title="音声ファイルを選択", filetypes=[("Audio files", "*.wav;*.mp3;*.ogg;*.flac" )])
            if p:
                self.audio_file_var.set(p)
                self.log(f"音声ファイルを選択: {p}")

        

        def save_bundle_file(self):
            p = filedialog.asksaveasfilename(title="名前をつけて保存", defaultextension=".zip", filetypes=[("ZIP archive","*.zip")])
            if not p:
                return
            audio = self.audio_file_var.get().strip()
            if not audio:
                messagebox.showerror("オーディオファイルがありません", "バンドルにはオーディオファイルが必要です。Audio を指定してください。")
                self.log("バンドル保存に失敗: オーディオファイルが未指定です")
                return
            # collect timeline data
            data = {"audio_file": os.path.basename(audio), "timeline": list(self.events)}
            try:
                with zipfile.ZipFile(p, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    # write timeline.json
                    zf.writestr("timeline.json", json.dumps(data, ensure_ascii=False, indent=4))
                    # add audio file under its basename
                    zf.write(audio, arcname=os.path.basename(audio))
                self.status_var.set(f"Saved bundle {os.path.basename(p)}")
                self.log(f"バンドルを保存しました: {p}")
            except Exception as exc:
                messagebox.showerror("Save error", f"バンドルの保存に失敗しました: {exc}")
                self.log(f"バンドルの保存に失敗しました: {exc}")

        def load_bundle_file(self):
            p = filedialog.askopenfilename(title="Open bundle (zip)", filetypes=[("ZIP archive","*.zip")])
            if not p:
                return
            # extract timeline.json and audio to temp
            try:
                with zipfile.ZipFile(p, "r") as zf:
                    if "timeline.json" not in zf.namelist():
                        messagebox.showerror("Invalid bundle", "timeline.json が見つかりません。")
                        self.log("timeline.json がバンドル内に見つかりませんでした")
                        return
                    text = zf.read("timeline.json").decode("utf-8")
                    data = json.loads(text)
                    audio_name = data.get("audio_file")
                    if not audio_name or audio_name not in zf.namelist():
                        # try to find first large audio-like file
                        candidates = [n for n in zf.namelist() if n.lower().endswith(('.wav','.mp3','.ogg','.flac'))]
                        if candidates:
                            audio_name = candidates[0]
                            self.log(f"想定された音声ファイルが見つからなかったため {audio_name} を使用します")
                        else:
                            messagebox.showerror("No audio", "バンドルにオーディオファイルが含まれていません。")
                            self.log("バンドルにオーディオファイルが含まれていません")
                            return
                    # extract audio to temp file
                    tmpdir = tempfile.mkdtemp(prefix="vtbundle_")
                    extracted_path = Path(tmpdir) / audio_name
                    with open(extracted_path, "wb") as f:
                        f.write(zf.read(audio_name))
                    # remember temp for cleanup
                    self._temp_audio_dirs.append(tmpdir)
                    self.log(f"バンドル内の音声を一時フォルダに展開: {extracted_path}")

                    # set audio and timeline
                    self.audio_file_var.set(str(extracted_path))
                    self.events.clear()
                    for entry in data.get("timeline", []):
                        self.events.append(dict(entry))
                    self.refresh_tree()
                    self.status_var.set(f"Loaded bundle {os.path.basename(p)}")
                    self.log(f"イベントを {len(self.events)} 件読み込みました")
                    self.log(f"バンドルを読み込みました: {p}")
            except zipfile.BadZipFile:
                messagebox.showerror("Invalid zip", "ZIP ファイルとして開けませんでした。")
                self.log("ZIP ファイルとして開けませんでした")
            except json.JSONDecodeError as exc:
                messagebox.showerror("JSON error", f"timeline.json の解析に失敗しました: {exc}")
                self.log(f"timeline.json の解析に失敗しました: {exc}")
            except Exception as exc:
                messagebox.showerror("Error", f"バンドルの読み込みに失敗しました: {exc}")
                self.log(f"バンドルの読み込みに失敗しました: {exc}")

        def _cleanup_tempdirs(self):
            dirs = list(self._temp_audio_dirs)
            for d in dirs:
                try:
                    shutil.rmtree(d)
                except Exception as exc:
                    self.log(f"一時フォルダの削除に失敗しました ({d}): {exc}")
            if dirs:
                self.log(f"一時フォルダを削除しました: {', '.join(dirs)}")
            self._temp_audio_dirs.clear()

        def _on_close(self):
            try:
                self._cleanup_tempdirs()
            finally:
                self.destroy()

        def log(self, message: str) -> None:
            def append() -> None:
                if not self.log_widget:
                    return
                timestamp = time.strftime("%H:%M:%S")
                self.log_widget.configure(state="normal")
                self.log_widget.insert("end", f"[{timestamp}] {message}\n")
                self.log_widget.see("end")
                self.log_widget.configure(state="disabled")

            self.after(0, append)

        # Pause control management
        def _add_pause_control(self, pause_id: str, t: float, resume_event: threading.Event) -> None:
            def create_button():
                btn = ttk.Button(self.frm_pause_controls, text=f"再開 {t:.3f}s", width=12)

                def _on_click():
                    try:
                        resume_event.set()
                    except Exception:
                        pass
                    try:
                        btn.configure(state="disabled")
                        btn.destroy()
                    except Exception:
                        pass
                    self.log(f"一時停止 {t:.3f}s を GUI から再開しました")

                btn.configure(command=_on_click)
                btn.pack(side="left", padx=4)
                # store reference
                if not hasattr(self, "_pause_control_widgets"):
                    self._pause_control_widgets = {}
                self._pause_control_widgets[pause_id] = btn

            self.after(0, create_button)

        def _remove_pause_control(self, pause_id: str) -> None:
            def remove_button():
                if hasattr(self, "_pause_control_widgets") and pause_id in self._pause_control_widgets:
                    try:
                        btn = self._pause_control_widgets.pop(pause_id)
                        btn.destroy()
                    except Exception:
                        pass

            self.after(0, remove_button)

        def _clear_pause_controls(self) -> None:
            # remove all pause control buttons
            def clear_all():
                if hasattr(self, "_pause_control_widgets"):
                    try:
                        for k, btn in list(self._pause_control_widgets.items()):
                            try:
                                btn.destroy()
                            except Exception:
                                pass
                        self._pause_control_widgets.clear()
                    except Exception:
                        pass
            self.after(0, clear_all)

        def refresh_tree(self):
            for it in self.tree.get_children():
                self.tree.delete(it)
            # sort by time
            self.events.sort(key=lambda e: float(e.get("time", 0.0)))
            for i, ev in enumerate(self.events):
                t = float(ev.get("time", 0.0))
                kind = ev.get("type", "press")
                data = ev.get("key") if kind == "press" else ev.get("flag", "")
                self.tree.insert("", "end", iid=str(i), values=(f"{t:.3f}", kind, data))

        def add_press(self):
            d = EventDialog(self, "Add Press", kind="press")
            if d.result:
                t, key = d.result
                self.events.append({"time": float(t), "type": "press", "key": str(key)})
                self.refresh_tree()
                self.log(f"押下キーイベントを追加: 時刻={float(t):.3f}s キー={key}")

        def add_pause(self):
            d = EventDialog(self, "Add Pause", kind="pause")
            if d.result:
                t, flag = d.result
                ev = {"time": float(t), "type": "pause"}
                if flag:
                    ev["flag"] = str(flag)
                self.events.append(ev)
                self.refresh_tree()
                if flag:
                    self.log(f"一時停止を追加: 時刻={float(t):.3f}s フラグ={flag}")
                else:
                    self.log(f"一時停止を追加: 時刻={float(t):.3f}s")

        def edit_event(self):
            sel = self.tree.selection()
            if not sel:
                return
            idx = int(sel[0])
            ev = self.events[idx]
            kind = ev.get("type", "press")
            d = EventDialog(self, "Edit", kind=kind, initial=ev)
            if d.result:
                t, val = d.result
                ev["time"] = float(t)
                if kind == "press":
                    ev["key"] = str(val)
                    ev.pop("flag", None)
                else:
                    if val:
                        ev["flag"] = str(val)
                    ev.pop("key", None)
                self.refresh_tree()
                self.log(f"イベントを編集: 時刻={float(t):.3f}s 種類={kind}")

        def delete_event(self):
            sel = self.tree.selection()
            if not sel:
                return
            idx = int(sel[0])
            del self.events[idx]
            self.refresh_tree()
            self.log(f"イベントを削除: インデックス={idx}")

        def move_selected(self, delta: int):
            sel = self.tree.selection()
            if not sel:
                return
            idx = int(sel[0])
            new = idx + delta
            if new < 0 or new >= len(self.events):
                return
            self.events[idx], self.events[new] = self.events[new], self.events[idx]
            self.refresh_tree()
            self.tree.selection_set(str(new))
            self.log(f"イベントを移動: {idx} -> {new}")

        def build_playback_data(self):
            schedule = []
            pauses = []
            flags = {}
            for ev in self.events:
                t = float(ev.get("time", 0.0))
                if ev.get("type") == "press":
                    schedule.append((t, str(ev.get("key", ""))))
                else:
                    pauses.append(t)
                    if "flag" in ev and ev["flag"]:
                        flags[str(ev["flag"])] = t
            schedule = sorted(schedule, key=lambda p: p[0])
            pauses = sorted(pauses)
            return schedule, pauses, flags

        def start_playback(self):
            audio = self.audio_file_var.get().strip()
            if not audio:
                messagebox.showerror("Error", "オーディオファイルが指定されていません。")
                self.log("オーディオファイルが指定されていないため再生できません")
                return
            # fully reset playback state and UI at Start
            try:
                self._fully_reset_playback_ui()
            except Exception:
                pass
            # create a fresh stop event for this session before launching threads/updaters
            self._stop_event = threading.Event()
            # set an immediate approximate total duration based on timeline
            try:
                approx_last = 0.0
                for t, _k in (ev for ev in [(float(e.get("time",0.0)), e.get("type","press")) for e in self.events] if True):
                    # 't' here is time only; we don't need type for max
                    approx_last = max(approx_last, t)
                schedule_tmp, pauses_tmp, _ = self.build_playback_data()
                if schedule_tmp:
                    approx_last = max(approx_last, schedule_tmp[-1][0])
                if pauses_tmp:
                    approx_last = max(approx_last, pauses_tmp[-1])
                self._playback_total_duration = max(10.0, approx_last + 5.0)
            except Exception:
                self._playback_total_duration = 0.0
            # bump playback session id to invalidate any previous handlers
            try:
                self._session_ctr += 1
                self._current_session = self._session_ctr
            except Exception:
                self._current_session = getattr(self, "_current_session", 0) + 1
            schedule, pauses, flags = self.build_playback_data()
            start_flag = self.start_flag_var.get().strip()
            start_offset = 0.0
            if start_flag:
                if start_flag in flags:
                    start_offset = flags[start_flag]
                    self.log(f"フラグ {start_flag} ({start_offset:.3f}s) から再生します")
                else:
                    messagebox.showwarning("Flag not found", "指定したフラグが見つかりません。先頭から再生します。")
                    self.log(f"指定したフラグ {start_flag} が見つからなかったため先頭から再生します")

            current_session = self._current_session

            def run_playback():
                def set_state(state: str) -> None:
                    self.after(0, lambda: self.set_widgets_state(state))

                def set_status(text: str) -> None:
                    self.after(0, lambda: self.status_var.set(text))

                def show_error(msg: str) -> None:
                    self.after(0, lambda: messagebox.showerror("Playback error", msg))

                try:
                    set_state("disabled")
                    set_status("Playing...")
                    self.log("再生を開始します")
                    # enable Stop button (stop event is already prepared)
                    # ensure current time is None so UI may fallback to get_pos until callback updates
                    self._playback_current_time = None
                    # playback metadata for progress updater
                    try:
                        # try to determine audio duration (seconds)
                        try:
                            pygame.mixer.init()
                            snd = pygame.mixer.Sound(audio)
                            total_dur = float(snd.get_length())
                        except Exception:
                            total_dur = None
                        try:
                            pygame.mixer.quit()
                        except Exception:
                            pass
                    except Exception:
                        total_dur = None
                    # fallback: use last event/pause time as approximate duration
                    if total_dur is None:
                        last_time = 0.0
                        if schedule:
                            last_time = max(last_time, schedule[-1][0])
                        if pauses:
                            last_time = max(last_time, pauses[-1])
                        total_dur = max(10.0, last_time + 5.0)
                    self._playback_total_duration = total_dur
                    try:
                        self.log(f"総時間: {total_dur:.3f}s")
                    except Exception:
                        pass
                    self._playback_start_offset = start_offset
                    self.after(0, lambda: self.stop_button.configure(state="normal"))
                    play_audio_with_hotkeys(
                        audio,
                        schedule,
                        pause_points=pauses,
                        start_offset=start_offset,
                        log_callback=self.log,
                        stop_event=self._stop_event,
                        pause_control_add=self._add_pause_control,
                        pause_control_remove=self._remove_pause_control,
                        progress_callback=lambda t: setattr(self, "_playback_current_time", float(t)),
                    )
                    self.log("再生が完了しました")
                except Exception as e:
                    err_msg = str(e)
                    if self._current_session == current_session:
                        show_error(err_msg)
                    self.log(f"再生中にエラーが発生しました: {err_msg}")
                finally:
                    if self._current_session == current_session:
                        set_status("Ready")
                        # if not stopped by user, place progress at end; otherwise keep reset
                        try:
                            user_stopped = hasattr(self, "_stop_event") and self._stop_event is not None and self._stop_event.is_set()
                            if (not user_stopped) and hasattr(self, "_playback_total_duration") and self._playback_total_duration:
                                self.after(0, lambda: self.progress.configure(value=self._playback_total_duration))
                        except Exception:
                            pass
                        self.after(0, lambda: self.stop_button.configure(state="disabled"))
                        set_state("normal")
                        # mark playback finished and stop updater
                        try:
                            self._playback_running = False
                            self._stop_progress_updater()
                        except Exception:
                            pass

            # mark running and start background playback thread
            self._playback_running = True
            self._playback_thread = threading.Thread(target=run_playback, daemon=True)
            self._playback_thread.start()

            # start UI-side progress updater
            try:
                self._progress_updater_running = True
                self._start_progress_updater()
            except Exception:
                pass
        def set_widgets_state(self, state: str):
            for child in self.winfo_children():
                try:
                    cast(Any, child).configure(state=state)
                except Exception:
                    pass

        def stop_playback(self) -> None:
            # Request stop for the running playback
            if hasattr(self, "_stop_event") and self._stop_event is not None:
                if not self._stop_event.is_set():
                    # mark not running as early as possible
                    try:
                        self._playback_running = False
                    except Exception:
                        pass
                    self._stop_event.set()
                    try:
                        pygame.mixer.music.stop()
                    except Exception:
                        pass
                    self.log("停止ボタンが押されました。再生を停止します。")
                    # disable stop button immediately
                    try:
                        self.stop_button.configure(state="disabled")
                    except Exception:
                        pass
                    # stop the progress updater and reset UI
                    try:
                        self._progress_updater_running = False
                        self._playback_current_time = 0.0
                        if hasattr(self, "progress") and self.progress is not None:
                            try:
                                self.progress.stop()
                            except Exception:
                                pass
                            try:
                                self.progress.configure(value=0)
                            except Exception:
                                pass
                        if hasattr(self, "time_label") and self.time_label is not None:
                            try:
                                self.time_label.configure(text="00:00.000 / 00:00.000")
                            except Exception:
                                pass
                    except Exception:
                        pass
            else:
                self.log("停止要求がありません（再生中ではありません）")

        def _start_progress_updater(self, interval_ms: int = 75) -> None:
            session_id = getattr(self, "_current_session", 0)
            def update():
                try:
                    # If a new session started, abandon this updater quietly
                    if getattr(self, "_current_session", 0) != session_id:
                        return
                    if not getattr(self, "_progress_updater_running", False):
                        return
                    total = getattr(self, "_playback_total_duration", None)
                    start_offset = getattr(self, "_playback_start_offset", 0.0)
                    running = getattr(self, "_playback_running", False)
                    # Prefer time reported by playback thread; fallback to mixer.get_pos()
                    current = getattr(self, "_playback_current_time", None)
                    if current is None:
                        pos_ms = -1
                        try:
                            pos_ms = pygame.mixer.music.get_pos()
                        except Exception:
                            pos_ms = -1
                        if pos_ms < 0:
                            current = 0.0
                        else:
                            current = pos_ms / 1000.0 + float(start_offset)

                    try:
                        if total and total > 0:
                            self.progress.configure(mode="determinate", maximum=total)
                            self.progress["value"] = min(current, total)
                        else:
                            # unknown duration -> indeterminate
                            self.progress.configure(mode="indeterminate")
                            try:
                                self.progress.start(50)
                            except Exception:
                                pass
                    except Exception:
                        pass

                    # update time label
                    try:
                        def fmt(sec: float) -> str:
                            if sec is None:
                                return "00:00.000"
                            total_ms = int(max(0.0, sec) * 1000)
                            ms = total_ms % 1000
                            s = (total_ms // 1000) % 60
                            m = (total_ms // 60000)
                            return f"{m:02d}:{s:02d}.{ms:03d}"

                        cur = current
                        tot = total if total is not None else 0.0
                        if hasattr(self, "time_label") and self.time_label is not None:
                            self.time_label.configure(text=f"{fmt(cur)} / {fmt(tot)}")
                    except Exception:
                        pass

                    # Stop updater only when playback is no longer running
                    user_stopped = hasattr(self, "_stop_event") and self._stop_event is not None and self._stop_event.is_set()
                    if not running or user_stopped:
                        try:
                            self.progress.stop()
                        except Exception:
                            pass
                        try:
                            if (not user_stopped) and total:
                                self.progress["value"] = total
                        except Exception:
                            pass
                        self._progress_updater_running = False
                        return
                finally:
                    if getattr(self, "_progress_updater_running", False):
                        self.after(interval_ms, update)

            # kick off immediately, then continue on interval
            self.after(0, update)

        def _stop_progress_updater(self) -> None:
            try:
                self._progress_updater_running = False
                self._playback_current_time = 0.0
                if hasattr(self, "progress") and self.progress is not None:
                    try:
                        self.progress.stop()
                    except Exception:
                        pass
                    try:
                        self.progress.configure(value=0)
                    except Exception:
                        pass
                if hasattr(self, "time_label") and self.time_label is not None:
                    try:
                        self.time_label.configure(text="00:00.000 / 00:00.000")
                    except Exception:
                        pass
            except Exception:
                pass

        def _build_progress_controls(self) -> None:
            # Destroy current children and recreate progress bar + time label
            try:
                if self.frm_progress is None:
                    return
                for child in list(self.frm_progress.winfo_children()):
                    try:
                        child.destroy()
                    except Exception:
                        pass
                self.progress = ttk.Progressbar(self.frm_progress, orient="horizontal", length=260, mode="determinate")
                self.progress.pack(side="left", padx=8)
                self.time_label = ttk.Label(self.frm_progress, text="00:00.000 / 00:00.000")
                self.time_label.pack(side="left", padx=6)
            except Exception:
                pass

        def _fully_reset_playback_ui(self) -> None:
            # Hard reset playback: stop thread/mixer, clear UI, rebuild progress controls
            try:
                # signal any previous playback to stop
                if hasattr(self, "_stop_event") and self._stop_event is not None:
                    try:
                        self._stop_event.set()
                    except Exception:
                        pass
                self._playback_running = False
            except Exception:
                pass
            # clear stop event so new session can create a clean one
            try:
                self._stop_event = None
            except Exception:
                pass
            # stop mixer completely
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            try:
                pygame.mixer.quit()
            except Exception:
                pass
            # attempt to join previous thread briefly
            try:
                if hasattr(self, "_playback_thread") and self._playback_thread is not None and self._playback_thread.is_alive():
                    self._playback_thread.join(timeout=0.2)
            except Exception:
                pass
            # clear pause controls
            try:
                self._clear_pause_controls()
            except Exception:
                pass
            # reset updater and UI
            self._stop_progress_updater()
            # rebuild the progress/time widgets to ensure pristine state
            try:
                self._build_progress_controls()
            except Exception:
                pass
            # reset internal timing
            self._playback_current_time = 0.0
            self._playback_total_duration = None
            self._playback_start_offset = 0.0
            # reset status label
            try:
                self.status_var.set("Ready")
            except Exception:
                pass

        def _reset_progress_ui(self) -> None:
            # used before a new playback starts to clear previous state
            try:
                self._progress_updater_running = False
            except Exception:
                pass
            try:
                self._playback_current_time = 0.0
            except Exception:
                pass
            if hasattr(self, "progress") and self.progress is not None:
                try:
                    self.progress.stop()
                except Exception:
                    pass
                try:
                    # ensure determinate mode and zero value
                    self.progress.configure(mode="determinate")
                except Exception:
                    pass
                try:
                    self.progress.configure(value=0)
                except Exception:
                    pass
            if hasattr(self, "time_label") and self.time_label is not None:
                try:
                    self.time_label.configure(text="00:00.000 / 00:00.000")
                except Exception:
                    pass

    class EventDialog(simpledialog.Dialog):
        def __init__(self, parent, title, kind="press", initial: Optional[Dict] = None):
            self.kind = kind
            self.initial = initial or {}
            self.result = None
            super().__init__(parent, title)

        def body(self, master):
            ttk.Label(master, text="Time (seconds):").grid(row=0, column=0, sticky="w")
            self.time_var = tk.StringVar(value=str(self.initial.get("time", "0.0")))
            ttk.Entry(master, textvariable=self.time_var).grid(row=0, column=1)

            if self.kind == "press":
                ttk.Label(master, text="Key: ").grid(row=1, column=0, sticky="w")
                self.val_var = tk.StringVar(value=str(self.initial.get("key", "")))
                ttk.Entry(master, textvariable=self.val_var).grid(row=1, column=1)
            else:
                ttk.Label(master, text="Flag (optional): ").grid(row=1, column=0, sticky="w")
                self.val_var = tk.StringVar(value=str(self.initial.get("flag", "")))
                ttk.Entry(master, textvariable=self.val_var).grid(row=1, column=1)

            return master

        def apply(self):
            t = float(self.time_var.get())
            v = self.val_var.get().strip()
            self.result = (t, v)

    app = TimelineEditor()
    app.mainloop()