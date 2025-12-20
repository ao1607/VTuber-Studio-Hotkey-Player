let events = [];
let totalDuration = 0;
let wavesurfer = null; // 波形表示用の WaveSurfer インスタンス

// 再生状態管理フラグ
let isPlaying = false; // 再生中かどうかのフラグ
let isPaused = false;  // 一時停止中かどうかのフラグ
let pausedAt = 0;    // 一時停止した時刻（再開時に使用）
let nextEventIndex = 0; // 次に発火すべきイベントのインデックス

// ズームレベル管理
let currentZoom = 0;

// --- 初期化処理 ---
document.addEventListener('DOMContentLoaded', () => {
    // WaveSurferの初期化
    wavesurfer = WaveSurfer.create({
        container: '#waveform',
        waveColor: '#4d4d60',      // 波形の色（未再生）
        progressColor: '#89b4fa',  // 波形の色（再生済み）
        cursorColor: '#ff5555',    // カーソルの色
        height: 80,
        responsive: true,
        normalize: true,           // 波形を最大化して見やすく
        backend: 'WebAudio',
        minPxPerSec: 0, // 最初は全体表示
        autoCenter: false, // 勝手にスクロールされると邪魔なのでOFF
        dragToSeek: true  // クリック＆ドラッグでシーク可能に
    });

    wavesurfer.setVolume(1.0); // 音量を 1.0 に設定
    wavesurfer.on('ready', () => {
        js_log("波形の生成が完了しました。");
        hideLoading();      // モーダルを消す
        setUIEnabled(true); // ボタンを押せるようにする
    });

    // 万が一エラーが起きた時も閉じ込められないようにする
    wavesurfer.on('error', (e) => {
        js_log("波形エラー: " + e);
        hideLoading();
        alert("波形の読み込みに失敗しましたの...");
    });    
    // ダブルクリックでイベントを自動追加する（必要ならコメント解除）

    // 1. 時間表示の更新 (再生中もドラッグ中も常に動く 'timeupdate' を使う)
    wavesurfer.on('timeupdate', (currentTime) => {
        document.getElementById('time-display').textContent = currentTime.toFixed(3) + "s";
    });

    // 2. イベントの発火チェック (これは再生中のみ動く 'audioprocess' のままでOK)
    wavesurfer.on('audioprocess', (currentTime) => {
        // 時間表示更新
        document.getElementById('time-display').textContent = currentTime.toFixed(3) + "s";

        // まだ発火していないイベントがあり、かつその時間が来た場合
        while (nextEventIndex < events.length) {
            const ev = events[nextEventIndex];
            
            // イベントの時間が現在時刻より「前」なら発火（少しのズレも許容）
            if (ev.time <= currentTime) {
                // "pause" タイプはJS側で制御
                if (ev.type === 'pause') {
                    wavesurfer.pause();
                    updateToggleIcon(false);
                    js_log(`Paused at ${ev.time.toFixed(2)}s`);
                } 
                // "press" タイプはPythonへ命令
                else if (ev.type === 'press') {
                    js_log(`Key: ${ev.key} at ${currentTime.toFixed(2)}s`);
                    eel.trigger_hotkey_py(ev.key)(); // Pythonを呼び出し
                }
                
                nextEventIndex++; // 次のイベントへ
            } else {
                // まだ時間が来ていないイベントならループを抜ける
                break; 
            }
        }
    });



    // シーク（手動移動）した時の処理
    wavesurfer.on('seek', () => {
        const currentTime = wavesurfer.getCurrentTime();
        document.getElementById('time-display').textContent = currentTime.toFixed(3) + "s";
        
        // 再生位置が変わったので、nextEventIndex を再計算
        // 「現在時刻より未来にある最初のイベント」を探す
        nextEventIndex = 0;
        for (let i = 0; i < events.length; i++) {
            if (events[i].time > currentTime) {
                nextEventIndex = i;
                break;
            }
            // 最後まで行ったら index は events.length になる
            if (i === events.length - 1) {
                nextEventIndex = events.length;
            }
        }
        // js_log(`Seeked to ${currentTime.toFixed(2)}s. Next Event Index: ${nextEventIndex}`);
    });

    // 再生終了時
    wavesurfer.on('finish', () => {
        updateToggleIcon(false);
        nextEventIndex = 0; // 最初に戻す
        wavesurfer.seekTo(0);
        js_log("再生終了");
    });


    setUIEnabled(false); // 初期状態ではUIを無効化



    const waveformContainer = document.querySelector('#waveform');
    
    waveformContainer.addEventListener('wheel', (e) => {
        // 音声が読み込まれていないときは何もしない
        if (!wavesurfer || wavesurfer.getDuration() === 0) return;
        
        // Shiftキー + ホイール = ズーム (拡大縮小)
        if (e.shiftKey) {
            e.preventDefault(); // ブラウザ標準の戻る/進むなどをキャンセル

            // ズーム感度（調整して好みに合わせるのですの）
            const zoomDelta = e.deltaY > 0 ? -10 : 10; 
            
            currentZoom += zoomDelta;
            
            // 範囲制限 (0 = 全体表示, 500 = かなり拡大)
            if (currentZoom < 0) currentZoom = 0;
            if (currentZoom > 500) currentZoom = 500;
            
            wavesurfer.zoom(currentZoom);
        } 
        // 通常ホイール = 横スクロール
        else {
            // コンテナがスクロール可能な状態（中身があふれている）なら
            if (waveformContainer.scrollWidth > waveformContainer.clientWidth) {
                e.preventDefault(); // 縦スクロールを防止
                
                // 横方向にスクロールさせる
                waveformContainer.scrollLeft += e.deltaY;
            }
        }
    }, { passive: false }); // preventDefaultを使うために passive: false が必須！
});

// UIの有効/無効を切り替える関数
function setUIEnabled(enabled) {
    // 1. ボタン類の disabled 属性切り替え
    const idsToDisable = ['btn-save', 'btn-add', 'in-time', 'in-type', 'in-key'];
    idsToDisable.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = !enabled;
    });

    // 2. 再生トグルボタン（div）のクラス切り替え
    const toggleBtn = document.getElementById('btn-toggle');
    if (toggleBtn) {
        if (enabled) {
            toggleBtn.classList.remove('disabled');
        } else {
            toggleBtn.classList.add('disabled');
        }
    }
}


// ローディングモーダルの表示/非表示
function showLoading() {
    document.getElementById('loading-overlay').style.display = 'flex';
}

function hideLoading() {
    document.getElementById('loading-overlay').style.display = 'none';
    // 既存の waveform-loading (波形エリア内の文字) も消しておく
    const innerLoading = document.getElementById('waveform-loading');
    if(innerLoading) innerLoading.style.display = 'none';
}



// --- Python (eel) から呼ばれる関数 ---

eel.expose(js_log);
function js_log(msg) {
    const box = document.getElementById('log-box');
    const line = document.createElement('div');
    
    const timeStr = new Date().toLocaleTimeString();
    
    // HTMLで色付けして流し込む
    // 「PS > [時刻] メッセージ」の形式にする
    line.innerHTML = `
        <span class="log-prompt">></span>
        <span class="log-time">[${timeStr}]</span>
        <span>${msg}</span>
    `;
    
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
}

// --- UI操作 ---

async function pickAudio() {

    showLoading();

    // Python 側から { full_path, rel_path } を含むオブジェクトが返る想定
    let data = await eel.select_audio_file()();
    
    if (data) {
        document.getElementById('audio-path-display').textContent = data.full_path;
        js_log("Audio Selected: " + data.full_path);
        
        // 波形読み込み開始（完了すると ready イベントで hideLoading が呼ばれる）
        loadWaveform(data.rel_path);
    } else {
        // キャンセルされた場合はローディングを消す
        hideLoading();
    }
}



async function loadBundle() {

    showLoading();

    // Python 側の関数を呼んでバンドルデータを取得
let data = await eel.load_bundle()();
    
    if (data) {
        document.getElementById('audio-path-display').textContent = data.audio_path;
        events = data.events;
        events.forEach(e => e.time = parseFloat(e.time));
        renderEvents();
        js_log("バンドルデータの復元が完了しました。");

        if (data.rel_path) {
            // 波形読み込み開始
            loadWaveform(data.rel_path);
        } else {
            // 波形がない場合（稀ですが）は手動で解除
            hideLoading();
            setUIEnabled(true);
        }
    } else {
        // キャンセルまたはエラー時
        hideLoading();
    }
}

// イベントを追加する
function addEvent() {
    const t = document.getElementById('in-time').value;
    const type = document.getElementById('in-type').value;
    const key = document.getElementById('in-key').value;

    if (!t) return;
    
    events.push({
        time: parseFloat(t),
        type: type,
        key: key
    });
    
    // 時間順にソート
    events.sort((a, b) => a.time - b.time);
    renderEvents();
}

// 指定したインデックスのイベントを削除
function deleteEvent(index) {
    events.splice(index, 1);
    renderEvents();
}

// イベントリストを DOM に再描画
function renderEvents() {
    const container = document.getElementById('event-list');
    container.innerHTML = '';
    
    events.forEach((ev, idx) => {
        const row = document.createElement('div');
        row.className = 'event-row';
        row.innerHTML = `
            <div>${ev.time.toFixed(3)}</div>
            <div>${ev.type}</div>
            <div>${ev.key || '-'}</div>
            <div><button onclick="deleteEvent(${idx})" style="padding:2px 5px; background: #d33;">×</button></div>
        `;
        container.appendChild(row);
    });
}

// 選択したタイプに応じてキー入力欄の表示/非表示を切り替える
function toggleInput() {
    const type = document.getElementById('in-type').value;
    const keyInput = document.getElementById('in-key');
    if (type === 'pause') {
        keyInput.style.display = 'none';
    } else {
        keyInput.style.display = 'inline-block';
    }
}

// ▼▼▼ トグルボタンのロジック ▼▼▼
async function togglePlayback() {
    if (!wavesurfer) return;

    if (wavesurfer.isPlaying()) {
        // 再生中 → 一時停止
        wavesurfer.pause();
        updateToggleIcon(false);
        js_log("Paused");
    } else {
        // 停止中 → 再生
        // 再生開始時にVTubeStudioにフォーカスを当てる
        eel.focus_window_py()(); 
        
        wavesurfer.play();
        updateToggleIcon(true);
        js_log("Playing...");
    }
}

// アイコンの切り替え（showPause: trueならPauseアイコンを表示）
function updateToggleIcon(showPause) {
    const iconPlay = document.getElementById('icon-play');
    const iconPause = document.getElementById('icon-pause');
    const btn = document.getElementById('btn-toggle');

    if (showPause) {
        iconPlay.style.display = 'none';
        iconPause.style.display = 'block';
        btn.classList.add('playing');
    } else {
        iconPlay.style.display = 'block';
        iconPause.style.display = 'none';
        btn.classList.remove('playing'); // Pause中も色を戻すかどうかはお好みで
    }
} 


async function saveBundle() {
    // 現在のイベントリストを JSON にして Python 側へ送信し、保存させる
    const data = {
        audio_file: document.getElementById('audio-path-display').textContent,
        events: events
    };
    await eel.save_bundle(JSON.stringify(data))();
}


function loadWaveform(url) {
    // WaveSurfer にオーディオを読み込ませる
    wavesurfer.load(url);
}