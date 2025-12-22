import sys
import os
# DLLの場所を通すおまじない

dll_path = os.path.dirname(sys.executable)
if os.path.isdir(dll_path):
    os.add_dll_directory(dll_path)
    # おまじない：環境変数 PATH にも追加しておくのですの
    os.environ['PATH'] = dll_path + os.pathsep + os.environ.get('PATH', '')

import eel
import json
import keyboard
import shutil
import tempfile
import zipfile
import pygetwindow as gw
from pathlib import Path
import subprocess
import bottle
import time

import requests
from packaging import version

CURRENT_VERSION = "v2.3.0" 
REPO_OWNER = "ao1607"
REPO_NAME = "VTube-Studio-Hotkey-Player"

eel.init('web')



class PrintToJsLogger(object):
    def __init__(self):
        self.terminal = sys.stdout  # 元の標準出力（ターミナル）を保存

    def write(self, message):
        # 1. まずはターミナルに出力（これがないと黒い画面に何も出なくなる）
        self.terminal.write(message)
        
        # 2. JavaScriptに送る
        # print()は改行コード "\n" だけを別途送ってくることがあるので、
        # 空白だけのメッセージは無視するようにするとログが綺麗になりますの
        text = message.strip()
        if text:
            try:
                # JavaScript側の js_log(msg) を呼び出す
                eel.js_log(text)
            except Exception:
                # Eelがまだ接続されていない時やエラー時は無視
                pass

    def flush(self):
        # ターミナルのフラッシュ処理
        self.terminal.flush()


sys.stdout = PrintToJsLogger()



def resource_path(relative_path):
    """ PyInstallerでexe化した時に正しいパスを取得するための関数 """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# --- グローバル変数 ---
STATE = {
    "audio_path": "",
    "key_duration": 0.08  # デフォルト値を追加
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
    $f.Filter = 'Audio Files (*.wav;*.mp3;*.ogg;*.m4a)|*.wav;*.mp3;*.ogg;*.m4a|All Files (*.*)|*.*';
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
    


@eel.expose
def update_key_duration_py(duration):
    """JSからキー押下時間の設定を受け取る"""
    try:
        val = float(duration)
        # 安全のため、極端な値は制限しておくといいですの
        if val < 0.01: val = 0.01
        if val > 1.0: val = 1.0
        STATE["key_duration"] = val
        print(f"Duration updated: {val}")
    except:
        pass




# ▼▼▼ 単純にキーを押すだけの関数 ▼▼▼
@eel.expose
def trigger_hotkey_py(key_str):
    """
    main.py のロジックを完全再現したホットキー実行関数
    JSから送られてくる "Right Shift+1" などを分解して、
    keyboardライブラリで確実に押下します。
    """
    print(f"Triggering: {key_str}") # デバッグ用ログ
    
    if not key_str:
        return

    # 1. キー文字列を分解して正規化
    # 例: "Right Shift+1" → ["right shift", "1"]
    # 例: "Ctrl+S" → ["ctrl", "s"]
    keys = [k.strip().lower() for k in key_str.split('+')]

    try:
        # 2. 修飾キーを含めて順番に「押し込み (Press)」
        for k in keys:
            keyboard.press(k)
        
        # 3. デフォルト 0.08秒 (80ms) 待機
        # これがないとVTube Studioが認識しないことがありますの
        time.sleep(STATE["key_duration"])
        
        # 4. 逆順に「離す (Release)」
        # 押した順序と逆（後に入れたキーから離す）のが作法ですの
        for k in reversed(keys):
            keyboard.release(k)
            
    except Exception as e:
        print(f"Hotkey Error: {e}")
        # エラーが起きてもキーが押しっぱなしにならないように救済
        for k in keys:
            try:
                keyboard.release(k)
            except:
                pass



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



@eel.expose
def check_for_updates():
    """
    GitHubから最新バージョンを確認する（リトライ機能付き）
    戻り値: { "update_available": bool, "latest_version": str, "url": str, "body": str }
    """
    api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
    max_retries = 3  # 最大3回までチャレンジしますの
    
    for attempt in range(max_retries):
        try:
            # リクエスト送信（タイムアウトは10秒）
            response = requests.get(api_url, timeout=10)
            
            # 通信成功！ (ステータスコード200)
            if response.status_code == 200:
                data = response.json()
                latest_tag = data.get("tag_name", "v0.0.0")

                v_current = version.parse(CURRENT_VERSION)
                v_latest = version.parse(latest_tag)
                
                # バージョン比較
                if v_latest > v_current:
                    return {
                        "update_available": True,
                        "current_version": CURRENT_VERSION,
                        "latest_version": latest_tag,
                        "url": data.get("html_url"),
                        "body": data.get("body", ""),
                        # zipのDLリンクを探す
                        "download_url": next((asset["browser_download_url"] for asset in data["assets"] if asset["name"].endswith(".zip")), None)
                    }
                elif v_current > v_latest:
                    # ★ここが追加点：現在バージョンの方が新しい場合（開発版）
                    return {
                        "update_available": False,
                        "is_dev_version": True, # これが目印ですの
                        "current_version": CURRENT_VERSION,
                        "latest_version": latest_tag
                    }
                else:
                    return {"update_available": False, "current_version": CURRENT_VERSION}
            
            # 200以外が返ってきたら、リトライせずにループを抜けますの（API制限など）
            break

        except requests.exceptions.RequestException as e:
            # タイムアウトや接続エラーなど
            print(f"Update check failed (Attempt {attempt+1}/{max_retries}): {e}")
            
            if attempt < max_retries - 1:
                time.sleep(2)  # 2秒待ってから再試行しますの
                continue
            else:
                # 3回やってもダメならエラーを返しますの
                return {"error": str(e)}

        except Exception as e:
            # その他の予期せぬエラー
            print(f"Update Check Error: {e}")
            return {"error": str(e)}
    
    return {"update_available": False}

# --- app.py の perform_update 関数を書き換え ---

@eel.expose
def perform_update(download_url):
    """
    更新を実行する
    1. ZIPダウンロード & 解凍
    2. 新しいファイル構成を確認
    3. 同期・削除・コピーを行うバッチファイルを生成して実行
    """
    if not download_url:
        return False

    try:
        eel.js_log("最新版をダウンロードしていますの...")
        
        # 1. ZIPをダウンロード
        response = requests.get(download_url, stream=True)
        zip_path = os.path.join(TEMP_DIR, "update.zip")
        
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # 2. 解凍先（一時フォルダ）
        extract_dir = os.path.join(TEMP_DIR, "update_extracted")
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_dir)

        # 3. アップデーターバッチファイルの作成
        current_exe = sys.executable
        current_dir = os.path.dirname(current_exe)
        
        # バッチファイルのコマンドをリストで構築
        commands = [
            "@echo off",
            "title Updating...",
            "echo Waiting for the application to close...",
            "ping 127.0.0.1 -n 3 > nul",  # アプリ終了待ち
        ]

        # パスを絶対パスに変換（バッチでのトラブル防止）
        extract_dir_abs = os.path.abspath(extract_dir)
        current_dir_abs = os.path.abspath(current_dir)

        # ▼▼▼ 1. webフォルダの同期（ミラーリング） ▼▼▼
        # 新しいZIPに 'web' フォルダがある場合のみ実行
        if os.path.exists(os.path.join(extract_dir, "web")):
            commands.append("echo Syncing web folder...")
            # robocopy /MIR ... フォルダを完全同期（古いファイルは削除される）
            # /NFL /NDL /NJH /NJS ... ログを抑制して画面を綺麗に
            cmd = f'robocopy "{extract_dir_abs}\\web" "{current_dir_abs}\\web" /MIR /NFL /NDL /NJH /NJS'
            commands.append(cmd)
            # robocopyは成功時にエラーコード1などを返す仕様なので、エラー判定をリセットする
            commands.append("if %ERRORLEVEL% LEQ 8 set ERRORLEVEL=0")

        # ▼▼▼ 2. Pythonランタイムフォルダの入替 ▼▼▼
        # 新しいZIPに 'python-x.x.x...' フォルダが含まれているかチェック
        has_new_python = any(f.startswith("python-") and os.path.isdir(os.path.join(extract_dir, f)) for f in os.listdir(extract_dir))
        
        if has_new_python:
            commands.append("echo Updating Python runtime...")
            # 現在のフォルダにある 'python-*' というフォルダを全て削除
            commands.append(f'for /d %%i in ("{current_dir_abs}\\python-*") do rmdir /S /Q "%%i"')
        
        # ▼▼▼ 3. 特定ファイルの削除チェック (app.py, start.vbs) ▼▼▼
        # 新しいZIPにこれらのファイルが入っていなければ、古い方を削除する
        check_files = ["app.py", "start.vbs"]
        
        for filename in check_files:
            if not os.path.exists(os.path.join(extract_dir, filename)):
                # 新しい方に無いなら、古い方を消すコマンドを追加
                commands.append(f'if exist "{current_dir_abs}\\{filename}" del /F /Q "{current_dir_abs}\\{filename}"')

        # ▼▼▼ 4. 全ファイルの統合コピー（上書き） ▼▼▼
        # webフォルダなどはrobocopyで済みだが、念のため全体を上書きコピーして確実に最新にする
        # （robocopyで消したくない 'temp_audio' などのユーザーデータはこのコマンドでは消えないので安全）
        commands.append("echo Updating all files...")
        commands.append(f'xcopy /E /Y "{extract_dir_abs}\\*" "{current_dir_abs}\\"')

        # 5. 再起動処理
        commands.append("echo Restarting application...")
        commands.append(f'start "" "{current_exe}"')


        # 自分自身(updater.bat)を削除する処理を、別プロセスに投げて自分はさっさと終了する
        # ping で2回ほど待機してから del するコマンドを裏で実行させる
        commands.append('start /b "" cmd /c "ping -n 2 127.0.0.1 > nul & del "%~f0""') 
        commands.append('exit')


        # バッチファイルを書き込み
        bat_content = "\n".join(commands)
        bat_path = os.path.join(current_dir, "updater.bat")
        
        with open(bat_path, "w", encoding="cp932") as f:
            f.write(bat_content)

        eel.js_log("更新準備完了。再起動します。")
        
        # バッチ起動して終了
        subprocess.Popen([bat_path], shell=True)
        time.sleep(1)
        sys.exit(0)

    except Exception as e:
        eel.js_log(f"更新エラー: {e}")
        return False


@eel.expose
def get_version():
    """現在のバージョンを返す"""
    return CURRENT_VERSION

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