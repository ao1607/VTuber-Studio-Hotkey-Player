# VTube Studio ホットキー自動再生ツール

Web UI（Eel）を用いた Windows 向けの小さなユーティリティです。GUI でタイムライン（キー押下 / 一時停止 / フラグ）を編集し、音声再生に同期して `Right Shift + <キー>` を自動送信します。音声はローカルファイルを `web/temp/` にコピーして再生・表示します。

## 主な機能

- 音声再生に同期したキー送信（`Right Shift + <キー>`）
- タイムラインの編集（時間・タイプ・キー）
- バンドル（ZIP）でタイムラインと音声をまとめて保存／読み込み
- 波形表示（WaveSurfer）および進捗同期（UI ← Python スレッド）

## 依存（主なもの）

- Python 3.11 以降（推奨）
- `eel`, `pygame`, `keyboard`, `pygetwindow` など（`requirements.txt` を参照）
- Windows（ファイルダイアログは PowerShell を使用）

## インストール（仮想環境推奨）

```powershell
pip install -r requirements.txt
```

## 実行方法

```powershell
python ./app.py
```

起動すると Eel によりブラウザ風 UI（ローカル）を開きます。UI 上で音声を選択・タイムライン編集・再生操作が可能です。

## バンドル（ZIP）構造

```
archive.zip
  ├─ timeline.json
  └─ <audio file>
```

`timeline.json` の想定フォーマット（例）:

```json
{
  "audio_file": "xxx.mp3",
  "timeline": [
    {"time": 1.2, "type": "press", "key": "A"},
    {"time": 5.0, "type": "pause"}
  ]
}
```

- アプリ内部では読み込み時に ZIP を展開し、音声ファイルを `web/temp/` にコピーして JavaScript から参照可能にします。
- 出力する JSON 形式は実装の都合で `audio_file` / `events` など若干の差異がありますが、現在の読み込みロジックは `timeline`（または `events`）を参照します。

## 一時ファイルについて

- 音声ファイルは `web/temp/` にコピーされます。新しいファイル選択やバンドル読み込み時に古い一時ファイルは上書き/削除されます。

## 再生・一時停止の挙動（現在の仕様）

- 再生は Python 側で行い、UI（JavaScript）は進捗表示と波形のシークを受け取ります。
- 一時停止（Pause）は JS から `toggle_pause_py(true/false)` を呼んで制御する設計です。Python 側では `STATE["pause_event"]`（`threading.Event`）で制御します。
- 以前は JS 側に「再開ボタン」を出す設計がありましたが、現在は UI 表示と同期する実装が簡略化されています。UI での再開ボタンを追加する場合は、JS と Python のプロトコル（Eel 関数）を追加してください。

## 重要な要素と HTML 例（UI 実装メモ）

- トグル再生ボタン（JS 側で `togglePlayback()` を呼ぶ）: `id="btn-toggle"`
- 再生/一時停止アイコン: `id="icon-play"`, `id="icon-pause"`
- 波形コンテナ: `id="waveform"`（WaveSurfer 用）

簡単なボタン例:

```html
<button id="btn-toggle" class="play-toggle" onclick="togglePlayback()">
  <span id="icon-play">▶</span>
  <span id="icon-pause" style="display:none">⏸</span>
</button>
```

## 既知の制限・注意事項

- 進捗表示・キー送信は Python スレッドから通知しています。スレッド同期のタイミングによっては UI 表示やキー送信に遅延が出る場合があります。
- フォーカス操作（VTube Studio を前面化）を試みますが、環境によって確実に前面化できないことがあります。重要な操作がある場合は、再生開始前に手動でフォーカスしてください。
- 現在の実装では一時停止中の UI 表示（再開ボタンの自動生成など）は簡略化されています。UI 側での一時停止管理が必要なら実装を拡張できます。

---

改善案やスクリーンショット、操作手順の追加など希望があれば指示ください。
