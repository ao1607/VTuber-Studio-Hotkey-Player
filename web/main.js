let events = [];
let totalDuration = 0;
let wavesurfer = null; // 波形表示用の WaveSurfer インスタンス



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
    });

    wavesurfer.setVolume(0); // 音量を 0 に設定（再生時の音声は Python 側で扱うため）

    // 波形をクリックしたときの処理（クリック位置の時刻を入力欄へ反映）
    wavesurfer.on('interaction', (newTime) => {
        // クリック位置の時刻を入力欄へ反映
        document.getElementById('in-time').value = newTime.toFixed(3);
    });
    
    // ダブルクリックでイベントを自動追加する（必要ならコメント解除）
    /*
    wavesurfer.on('dblclick', () => {
        addEvent(); // 現在入力されている時刻（直前のクリックでセット済）で追加
    });
    */
});



// --- Python (eel) から呼ばれる関数 ---

eel.expose(js_log);
function js_log(msg) {
    const box = document.getElementById('log-box');
    const line = document.createElement('div');
    line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
}

eel.expose(js_set_duration);
function js_set_duration(duration) {
    totalDuration = duration;
    js_log("Total Duration set to: " + duration.toFixed(2) + "s");
}

eel.expose(js_update_progress);
function js_update_progress(currentTime) {
    document.getElementById('time-display').textContent = currentTime.toFixed(3) + "s";
    
    // ▼▼▼ 修正: 進捗バーの更新処理を削除し、波形操作だけにする ▼▼▼
    if (totalDuration > 0 && wavesurfer) {
        // 再生中はPythonがマスターなので、波形側はシークするだけ（音は出さない）
        if (!wavesurfer.isPlaying()) {
            // 0.0 ~ 1.0 の割合で指定
            let ratio = currentTime / totalDuration;
            // 念のため範囲制限
            if (ratio < 0) ratio = 0;
            if (ratio > 1) ratio = 1;
            
            wavesurfer.seekTo(ratio);
        }
    }
}


eel.expose(js_on_stop);
// 再生停止時に呼ばれる（Python から呼び出される）
function js_on_stop() {
    document.getElementById('btn-play').disabled = false;
    document.getElementById('btn-stop').disabled = true;
    js_log("Stopped.");
}

// --- UI操作 ---

async function pickAudio() {
    // Python 側から { full_path, rel_path } を含むオブジェクトが返る想定
    let data = await eel.select_audio_file()();
    if (data) {
        document.getElementById('audio-path-display').textContent = data.full_path;
        js_log("Audio Selected: " + data.full_path);
        
        // 波形の読み込み
        loadWaveform(data.rel_path);
    }
}



async function loadBundle() {
    // Python 側の関数を呼んでバンドルデータを取得
    let data = await eel.load_bundle()();
    
    if (data) {
        // 音声パスの表示更新
        document.getElementById('audio-path-display').textContent = data.audio_path;
        
        // イベントリストの更新
        events = data.events;
        // 型変換（time を数値に変換）
        events.forEach(e => e.time = parseFloat(e.time));
        
        renderEvents();
        js_log("バンドルデータの復元が完了しました。");

        // 波形読み込み
        if (data.rel_path) {
            loadWaveform(data.rel_path);
        }
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

async function startPlayback() {
    const offset = document.getElementById('start-offset').value;
    document.getElementById('btn-play').disabled = true;
    document.getElementById('btn-stop').disabled = false;
    
    // 音声ファイル長の取得は別途必要ですが、ここではイベントリストを Python 側へ渡して再生を開始
    await eel.start_playback_py(events, offset)();
}

// 再生停止を Python に通知
function stopPlayback() {
    eel.stop_playback_py();
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
    const loading = document.getElementById('waveform-loading');
    loading.style.display = 'block';
    
    // WaveSurfer にオーディオを読み込ませる
    wavesurfer.load(url);
    
    wavesurfer.on('ready', () => {
        loading.style.display = 'none';
        js_log("波形の生成が完了しました。");
    });
}