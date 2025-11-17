# VTube Studio ホットキー自動再生ツール

GUIでタイムライン (キー押下/一時停止/フラグ) を編集し、音声再生に同期して `Right Shift + <キー>` を自動送信します。バンドルZIPで `timeline.json` と音声をまとめて保存/読み込み可能。

## 依存

- Python 3.11 以降推奨
- `pygame`, `keyboard`, `pygetwindow` (requirements.txt 参照)
- Tkinter (標準添付)

## インストール (仮想環境推奨)

```powershell
pip install -r requirements.txt
```
※exeファイルをダウンロードし使用することで、インストールせずにそのまま実行&使用できます。

## 実行

```powershell
python ./main.py
```

## バンドルZIP構造

```
archive.zip
  ├─ timeline.json
  └─ <audio file>
```
`timeline.json` 内部: `{"audio_file":"xxx.mp3","timeline":[{"time":1.2,"type":"press","key":"A"}, {"time":5.0,"type":"pause","flag":"1"}]}`

## 一時フォルダの掃除

ZIP読み込み時に音声を `vtbundle_` プレフィックスの一時フォルダへ展開。アプリ終了 (ウィンドウ閉じ) で自動削除。

## 既知の注意

- 連続再生中の進捗表示は内部スレッド同期に依存。表示が停止した場合は再生を一度停止して再度開始。
- VTube Studio を確実に前面に出したい場合は、再生開始押下後のカウントダウンで手動でクリックしてください。
