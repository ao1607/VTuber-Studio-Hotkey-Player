import eel
import sys
import os
import json
import threading
import keyboard
import shutil
import tempfile
import zipfile
import pygetwindow as gw
from pathlib import Path
import subprocess

# --- グローバル変数 ---
STATE = {
    "audio_path": "",
}

TEMP_DIR = os.path.join(os.path.dirname(__file__), 'web', 'temp')
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# --- ユーティリティ関数 ---

def _copy_to_web_temp(src_path: str) -> str:
    """音声をweb/tempにコピーし、Eelからアクセス可能な相対パスを返す"""
    try:
        # 既存の一時ファイルを削除
        for f in os.listdir(TEMP_DIR):
            try:
                os.remove(os.path.join(TEMP_DIR, f))
            except: pass
        
        filename = os.path.basename(src_path)
        dest_path = os.path.join(TEMP_DIR, filename)
        shutil.copy2(src_path, dest_path)
        return f"temp/{filename}"
    except Exception as e:
        print(f"Copy Error: {e}")
        return ""

def _show_powershell_dialog(cmd):
    """PowerShellダイアログヘルパー"""
    ps_cmd = [
        "powershell", "-noprofile", "-Sta", "-command", 
        f"Add-Type -AssemblyName System.Windows.Forms; {cmd}"
    ]
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        result = subprocess.run(
            ps_cmd, capture_output=True, text=True, startupinfo=startupinfo
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"Dialog Error: {e}")
        return ""

# --- Eelから呼ばれる関数 ---

@eel.expose
def select_audio_file():
    cmd = """
    $f = New-Object System.Windows.Forms.OpenFileDialog;
    $f.Filter = 'Audio Files (*.wav;*.mp3;*.ogg)|*.wav;*.mp3;*.ogg|All Files (*.*)|*.*';
    $f.Title = '音声ファイルを選択してくださいですの';
    if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Host $f.FileName }
    """
    original_path = _show_powershell_dialog(cmd)
    
    if original_path:
        STATE["audio_path"] = original_path
        rel_path = _copy_to_web_temp(original_path)
        return {"full_path": original_path, "rel_path": rel_path}
    return None

@eel.expose
def save_bundle(data_json):
    cmd = """
    $f = New-Object System.Windows.Forms.SaveFileDialog;
    $f.Filter = 'ZIP Archive (*.zip)|*.zip';
    $f.DefaultExt = 'zip';
    $f.Title = 'バンドルを保存する場所を選ぶのですの';
    if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Host $f.FileName }
    """
    path = _show_powershell_dialog(cmd)
    if not path or not STATE["audio_path"]: return
    
    data = json.loads(data_json)
    try:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("timeline.json", json.dumps(data, indent=4))
            zf.write(STATE["audio_path"], arcname=os.path.basename(STATE["audio_path"]))
        eel.js_log(f"保存しました: {path}")
    except Exception as e:
        eel.js_log(f"保存エラー: {e}")

@eel.expose
def load_bundle():
    cmd = """
    $f = New-Object System.Windows.Forms.OpenFileDialog;
    $f.Filter = 'ZIP Archive (*.zip)|*.zip';
    $f.Title = '読み込むバンドルを選択してくださいですの';
    if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Host $f.FileName }
    """
    path = _show_powershell_dialog(cmd)
    if not path: return None

    try:
        with tempfile.TemporaryDirectory() as extract_dir:
            with zipfile.ZipFile(path, 'r') as zf:
                zf.extractall(extract_dir)
                if "timeline.json" not in zf.namelist():
                    eel.js_log("エラー: timeline.jsonが見つかりません")
                    return None
                
                timeline_path = os.path.join(extract_dir, "timeline.json")
                with open(timeline_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                audio_filename = data.get("audio_file")
                extracted_audio_path = ""
                if audio_filename:
                    extracted_audio_path = os.path.join(extract_dir, audio_filename)
                
                if not extracted_audio_path or not os.path.exists(extracted_audio_path):
                    for f in os.listdir(extract_dir):
                        if f.endswith(('.wav', '.mp3', '.ogg')):
                            extracted_audio_path = os.path.join(extract_dir, f)
                            break
                
                if not extracted_audio_path or not os.path.exists(extracted_audio_path):
                    eel.js_log("エラー: 音声ファイルが見つかりません")
                    return None
                
                rel_path = _copy_to_web_temp(extracted_audio_path)
                final_audio_path = os.path.join(TEMP_DIR, os.path.basename(extracted_audio_path))
                STATE["audio_path"] = final_audio_path
                
                return {
                    "audio_path": final_audio_path,
                    "rel_path": rel_path,
                    "events": data.get("events", [])
                }
    except Exception as e:
        eel.js_log(f"読み込みエラー: {e}")
        return None

# ▼▼▼ 単純にキーを押すだけの関数 ▼▼▼
@eel.expose
def trigger_hotkey_py(key):
    """JSから呼ばれてホットキーを送信する"""
    try:
        # 文字列が空なら何もしない
        if not key: return

        # VTSへのフォーカスはJS側で再生開始時に一度呼ぶ設計になっているが、
        # ここで呼ぶとより確実。ただし動作が重くなる可能性あり。
        # focus_window_py() 

        # keyboard.send は "ctrl+s" のような複合キーを自動で処理してくれますの
        # 以前のように無理やり Right Shift を押す必要はありませんの
        keyboard.send(key)
        
    except Exception as e:
        print(f"Key Error: {e}")
@eel.expose
def focus_window_py():
    """再生開始時にVTubeStudioをアクティブにする"""
    try:
        windows = gw.getWindowsWithTitle("VTube Studio")
        if windows:
            win = windows[0]
            if win.isMinimized: win.restore()
            win.activate()
    except:
        pass

# --- Main ---
if __name__ == "__main__":
    eel.init('web')
    # Chromeの起動オプションを設定
    chrome_flags = [
        '--disable-extensions',   # 拡張機能を無効化（これが本命）
        '--disable-plugins',      # 余計なプラグインも無効化
        '--incognito',            # シークレットモードで起動（履歴もクッキーも残さない完全な新品状態）
        '--no-first-run',         # 初回起動時の「Chromeへようこそ」的なやつをスキップ
        '--no-default-browser-check' # デフォルトブラウザのチェックをスキップ
    ]
eel.start('index.html', size=(900, 700), cmdline_args=chrome_flags)