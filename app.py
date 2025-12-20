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
import bottle



def resource_path(relative_path):
    """ PyInstallerでexe化した時に正しいパスを取得するための関数 """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# --- グローバル変数 ---
STATE = {
    "audio_path": "",
}

if hasattr(sys, 'frozen'):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 実際に保存する場所（webフォルダの中ではなく、exeの隣に独立させる方がトラブルが少ないですの）
TEMP_DIR = os.path.join(BASE_DIR, 'temp_audio') 
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)


# --- ユーティリティ関数 ---

def _copy_to_web_temp(src_path: str) -> str:
    """音声を一時フォルダにコピーし、Eelからアクセス可能なパスを返す"""
    try:
        # 既存の一時ファイルを削除
        for f in os.listdir(TEMP_DIR):
            try:
                os.path.join(TEMP_DIR, f)
                os.remove(os.path.join(TEMP_DIR, f))
            except: pass
        
        # 元の拡張子（.wav や .mp3）だけ抜き出す
        ext = os.path.splitext(src_path)[1]
        
        # 固定の安全な名前にする（例: playing.wav）
        safe_filename = f"playing{ext}"
        
        dest_path = os.path.join(TEMP_DIR, safe_filename)
        shutil.copy2(src_path, dest_path)
        
        # Eel側にはこの「安全な名前」を教える
        return f"temp_audio/{safe_filename}"
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
    $f.Title = '音声ファイルを選択してくれですの';
    $d = New-Object System.Windows.Forms.Form;
    $d.TopMost = $true;
    $d.Opacity = 0;
    $d.ShowInTaskbar = $false;
        if ($f.ShowDialog($d) -eq [System.Windows.Forms.DialogResult]::OK) { Write-Host $f.FileName }
    $d.Dispose();
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
    $f.Title = 'バンドルを保存する場所を選びますの';
    $d = New-Object System.Windows.Forms.Form;
    $d.TopMost = $true;
    $d.Opacity = 0;
    $d.ShowInTaskbar = $false;
    if ($f.ShowDialog($d) -eq [System.Windows.Forms.DialogResult]::OK) { Write-Host $f.FileName }
    $d.Dispose();
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
    $f.Title = '読み込むバンドルを選択しろですの';
    $d = New-Object System.Windows.Forms.Form;
    $d.TopMost = $true;
    $d.Opacity = 0;
    $d.ShowInTaskbar = $false;
    if ($f.ShowDialog($d) -eq [System.Windows.Forms.DialogResult]::OK) { Write-Host $f.FileName }
    $d.Dispose();
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
    # ▼▼▼ 3. initの場所を修正するのですの！ ▼▼▼
    # webフォルダの正しいパスを取得して指定
    eel.init(resource_path('web'))
    
    # Chromeの起動オプション
    chrome_flags = [
        '--disable-extensions',
        '--disable-plugins',
        '--incognito',
        '--no-first-run',
        '--no-default-browser-check'
    ]
    @bottle.route('/temp_audio/<filename>')
    def serve_temp_audio(filename):
        # TEMP_DIR からファイルを直接探して返す最強の命令ですの
        return bottle.static_file(filename, root=TEMP_DIR)

    eel.start('index.html', size=(900, 650), cmdline_args=chrome_flags, port=0)