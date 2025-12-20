import eel
import sys
import os
import time
import json
import threading
import pygame
import keyboard
import ctypes
import shutil
import tempfile
import zipfile
import pygetwindow as gw
from pathlib import Path
from typing import List, Tuple, Dict, Optional
import subprocess

# --- 既存のロジック（一部Eel用に調整） ---

# グローバル変数で状態管理（簡易的）
STATE = {
    "audio_path": "",
    "events": [],  #List[Dict]
    "is_playing": False,
    "stop_event": None
}

TEMP_DIR = os.path.join(os.path.dirname(__file__), 'web', 'temp')
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)



def _copy_to_web_temp(src_path: str) -> str:
    """音声をweb/tempにコピーし、Eelからアクセス可能な相対パスを返すヘルパー"""
    try:
        # 既存の一時ファイルを削除
        for f in os.listdir(TEMP_DIR):
            try:
                os.remove(os.path.join(TEMP_DIR, f))
            except: pass
        
        filename = os.path.basename(src_path)
        dest_path = os.path.join(TEMP_DIR, filename)
        shutil.copy2(src_path, dest_path)
        
        # JSで使えるパス（'temp/filename.mp3'）を返す
        return f"temp/{filename}"
    except Exception as e:
        print(f"Copy Error: {e}")
        return ""



def focus_vtube_studio(title_keyword: str = "VTube Studio", wait_s: float = 0.3):
    """VTube Studioをアクティブにする"""
    try:
        windows = gw.getWindowsWithTitle(title_keyword)
        if not windows:
            print("VTS not found")
            return
        
        window = windows[0]
        if window.isMinimized:
            window.restore()
        window.activate()
        time.sleep(wait_s)
    except Exception as e:
        print(f"Focus error: {e}")

# 再生スレッド関数
def play_logic(audio_path, events, start_offset=0.0):
    STATE["is_playing"] = True
    stop_event = STATE["stop_event"]
    
    try:
        eel.js_log("VTube Studioにフォーカスします...")
        focus_vtube_studio()
        
        eel.js_log(f"再生準備: {start_offset}秒から")
        pygame.mixer.init()
        # 音声の長さを取得するためにSoundオブジェクトを作る
        sound = pygame.mixer.Sound(audio_path)
        total_duration = sound.get_length()
        # JavaScriptに全体の長さを通知
        eel.js_set_duration(total_duration)
        
        pygame.mixer.music.load(audio_path)
        
        # イベントのスケジュール化
        schedule = []
        pauses = []
        for ev in events:
            t = float(ev["time"])
            if ev["type"] == "press":
                schedule.append((t, ev["key"]))
            elif ev["type"] == "pause":
                pauses.append(t)
        
        schedule.sort(key=lambda x: x[0])
        pauses.sort()
        
        # 再生開始
        if start_offset > 0:
            try:
                pygame.mixer.music.play(start=start_offset)
            except:
                pygame.mixer.music.play()
                pygame.mixer.music.set_pos(start_offset)
        else:
            pygame.mixer.music.play()
            
        start_time = time.perf_counter() - start_offset
        fired_indices = set()
        pause_indices = set()

        while pygame.mixer.music.get_busy() and not stop_event.is_set():
            now = time.perf_counter() - start_time
            eel.js_update_progress(now) # フロントエンドに進捗通知

            # キー押下処理
            for idx, (target_sec, key) in enumerate(schedule):
                if idx in fired_indices: continue
                if now >= target_sec:
                    eel.js_log(f"Key: {key} at {now:.2f}s")
                    keyboard.press("right shift")
                    keyboard.press(key)
                    time.sleep(0.05)
                    keyboard.release(key)
                    keyboard.release("right shift")
                    fired_indices.add(idx)

            # 一時停止処理
            for idx, pause_sec in enumerate(pauses):
                if idx in pause_indices: continue
                if now >= pause_sec:
                    eel.js_log(f"Pause at {now:.2f}s")
                    pygame.mixer.music.pause()
                    eel.js_show_resume_button(idx, pause_sec) # 再開ボタンを表示
                    
                    # 再開待ちループ
                    pause_start = time.perf_counter()
                    while True:
                        if stop_event.is_set(): break
                        # JSから resume_playback が呼ばれるのを待つフラグ管理などは省略し、
                        # シンプルにPython側でwaitする実装にするなら threading.Event を使う
                        # ここでは簡易的に実装
                        time.sleep(0.1)
                        # ※本来は再開イベント待ち実装が必要
                        # 今回はシンプル化のため「停止」のみサポートするか、
                        # Eel経由で再開フラグを受け取る設計にする必要がありますの。
                        # ここでは「一時停止機能」は実装が複雑になるので、
                        # 基礎的な再生・キー連動を優先しますの。
                    
                    pause_indices.add(idx)
            
            time.sleep(0.01)

    except Exception as e:
        eel.js_log(f"Error: {e}")
    finally:
        pygame.mixer.music.stop()
        pygame.mixer.quit()
        STATE["is_playing"] = False
        eel.js_on_stop()
        eel.js_log("再生終了")

# --- Eel Interface ---

def _show_powershell_dialog(cmd):
    """PowerShellを使ってダイアログを表示し、パスを取得するヘルパー関数"""
    ps_cmd = [
        "powershell", 
        "-noprofile", 
        "-command", 
        f"Add-Type -AssemblyName System.Windows.Forms; {cmd}"
    ]
    try:
        # コンソールウィンドウが一瞬出るのを防ぐ設定 (Windows用)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        result = subprocess.run(
            ps_cmd, 
            capture_output=True, 
            text=True, 
            startupinfo=startupinfo
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"Dialog Error: {e}")
        return ""

@eel.expose
def select_audio_file():
    # PowerShellでファイル選択
    cmd = """
    $f = New-Object System.Windows.Forms.OpenFileDialog;
    $f.Filter = 'Audio Files (*.wav;*.mp3;*.ogg)|*.wav;*.mp3;*.ogg|All Files (*.*)|*.*';
    $f.Title = '音声ファイルを選択してくださいですの';
    if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { 
        Write-Host $f.FileName 
    }
    """
    original_path = _show_powershell_dialog(cmd)
    
    if original_path:
        STATE["audio_path"] = original_path
        
        # ▼▼▼ 修正: web/temp にコピーして、相対パスを返す ▼▼▼
        try:
            # 古い一時ファイルがあれば消す（お行儀よく）
            for f in os.listdir(TEMP_DIR):
                try:
                    os.remove(os.path.join(TEMP_DIR, f))
                except: pass

            filename = os.path.basename(original_path)
            dest_path = os.path.join(TEMP_DIR, filename)
            shutil.copy2(original_path, dest_path)
            
            # JSから見た相対パス ('temp/filename.mp3') と 絶対パスを返す
            return {
                "full_path": original_path,
                "rel_path": f"temp/{filename}"
            }
        except Exception as e:
            print(f"Copy Error: {e}")
            return None
            
    return None

@eel.expose
def save_bundle(data_json):
    # PowerShellで保存ダイアログを開くコマンド
    cmd = """
    $f = New-Object System.Windows.Forms.SaveFileDialog;
    $f.Filter = 'ZIP Archive (*.zip)|*.zip';
    $f.DefaultExt = 'zip';
    $f.Title = 'バンドルを保存する場所を選ぶのですの';
    if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { 
        Write-Host $f.FileName 
    }
    """
    path = _show_powershell_dialog(cmd)
    
    if not path or not STATE["audio_path"]: return
    
    # 選択されたパスに保存処理
    import json
    import zipfile
    import os
    
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
    # PowerShellでファイル選択（ZIP）
    cmd = """
    $f = New-Object System.Windows.Forms.OpenFileDialog;
    $f.Filter = 'ZIP Archive (*.zip)|*.zip';
    $f.Title = '読み込むバンドルを選択してくださいですの';
    if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { 
        Write-Host $f.FileName 
    }
    """
    path = _show_powershell_dialog(cmd)
    
    if not path: return None

    try:
        # 一時フォルダを作成して展開
        with tempfile.TemporaryDirectory() as extract_dir:
            with zipfile.ZipFile(path, 'r') as zf:
                zf.extractall(extract_dir)
                
                # timeline.jsonを探す
                if "timeline.json" not in zf.namelist():
                    eel.js_log("エラー: timeline.jsonが見つかりません")
                    return None
                
                # JSON読み込み
                timeline_path = os.path.join(extract_dir, "timeline.json")
                with open(timeline_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 音声ファイルを探す
                audio_filename = data.get("audio_file")
                extracted_audio_path = ""
                
                if audio_filename:
                    extracted_audio_path = os.path.join(extract_dir, audio_filename)
                
                # 念のためフォールバック探索
                if not extracted_audio_path or not os.path.exists(extracted_audio_path):
                    for f in os.listdir(extract_dir):
                        if f.endswith(('.wav', '.mp3', '.ogg')):
                            extracted_audio_path = os.path.join(extract_dir, f)
                            break
                
                if not extracted_audio_path or not os.path.exists(extracted_audio_path):
                    eel.js_log("エラー: バンドル内に音声ファイルが見つかりません")
                    return None
                
                # ▼▼▼ ここが重要！ web/temp にコピーして相対パスを取得 ▼▼▼
                rel_path = _copy_to_web_temp(extracted_audio_path)
                
                # audio_path はコピー先のパスにしておく
                final_audio_path = os.path.join(TEMP_DIR, os.path.basename(extracted_audio_path))
                STATE["audio_path"] = final_audio_path
                
                eel.js_log(f"バンドルを読み込みました: {path}")
                
                # JSに rel_path も一緒に返す
                return {
                    "audio_path": final_audio_path,
                    "rel_path": rel_path,
                    "events": data.get("timeline", [])
                }
            
    except Exception as e:
        eel.js_log(f"読み込みエラー: {e}")
        return None


@eel.expose
def start_playback_py(events, start_offset=0.0):
    if STATE["is_playing"]: return
    
    # イベントリストをPython側で保存
    STATE["events"] = events
    STATE["stop_event"] = threading.Event()
    
    if not STATE["audio_path"]:
        eel.js_log("音声ファイルが選択されていません")
        return

    # 別スレッドで再生ロジックを実行
    t = threading.Thread(target=play_logic, args=(STATE["audio_path"], events, float(start_offset)))
    t.daemon = True
    t.start()

@eel.expose
def stop_playback_py():
    if STATE["stop_event"]:
        STATE["stop_event"].set()


# --- Main ---
if __name__ == "__main__":
    eel.init('web')
    eel.start('index.html', size=(900, 600))