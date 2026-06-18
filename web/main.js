let events = [];
let totalDuration = 0;
let wavesurfer = null; // 波形表示用の WaveSurfer インスタンス
let wsRegions = null; // WaveSurfer Regions プラグインインスタンス

let nextEventIndex = 0; // 次に発火すべきイベントのインデックス


// 設定管理オブジェクト（デフォルト値）
let appConfig = {
    keyDuration: 0.08,
    skipSeconds: 10,
    volume: 1.0,
    autoScroll: false
};



function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[char]));
}

function updateNextEventIndex() {
    const currentTime = wavesurfer.getCurrentTime();
    nextEventIndex = 0;
    
    for (let i = 0; i < events.length; i++) {
        // 現在時刻より「未来」にある最初のイベントを探す
        // ※ 0.1秒くらいの誤差は許容して「これから来る」とみなすとなお良しですの
        if (events[i].time > currentTime) {
            nextEventIndex = i;
            return;
        }
    }
    // 全部過去のイベントなら、最後まで終わったことにする
    nextEventIndex = events.length;
}


// ズームレベル管理
let currentZoom = 0;

// --- 初期化処理 ---
document.addEventListener('DOMContentLoaded', () => {


    loadSettings();
    initVersion();

    checkUpdate(true);
    
    document.addEventListener('contextmenu', (e) => {
        e.preventDefault();
    });

    // WaveSurferの初期化
    wavesurfer = WaveSurfer.create({
        container: '#waveform',
        waveColor: '#4d4d60',      // 波形の色（未再生）
        progressColor: '#89b4fa',  // 波形の色（再生済み）
        cursorColor: '#ff5555',    // カーソルの色
        height: 90,           // 波形の高さ
        responsive: true,
        normalize: true,           // 波形を最大化して見やすく
        backend: 'WebAudio',
        minPxPerSec: 0, // 最初は全体表示
        autoCenter: appConfig.autoScroll, // 勝手にスクロールされると邪魔なのでOFF
        dragToSeek: true,  // クリック＆ドラッグでシーク可能に

        plugins: [
            WaveSurfer.Regions.create(),
            WaveSurfer.Timeline.create({
                container: '#wave-timeline', // さっき作ったdivのIDを指定
                height: 20,                  // 目盛りの高さ（お好みで調整）
                style: {
                    color: '#89b4fa',        // 文字の色（テーマに合わせて青っぽくしてみたぞ）
                    fontSize: '10px'
                }
            })
        ],
    });

    wsRegions = wavesurfer.plugins[0];

    wavesurfer.setVolume(appConfig.volume); // 音量を設定

    wavesurfer.on('ready', () => {
        // WaveSurferが生成したラッパー要素を取得
        const wrapper = document.querySelector('#waveform');        
        
        wrapper.addEventListener('contextmenu', (e) => {
            e.preventDefault(); // デフォルトの右クリックメニューを出さない

            // 1. コンテナの表示位置を取得
            const rect = wrapper.getBoundingClientRect();

            // 2. クリック位置（コンテナ左端からの相対位置）
            const xInView = e.clientX - rect.left;
            
            // 3. WaveSurferから「現在のスクロール量」を取得する（これが重要！）
            // ※ wrapper.scrollLeft だと、Shadow DOM等の関係で正しく取れないことがあるのですの
            const scrollLeft = wavesurfer.getScroll();
            
            // 4. WaveSurfer内部の描画ラッパーから「本当の全体幅」を取得する
            const totalWidth = wavesurfer.renderer.wrapper.scrollWidth;

            // 5. 時間を計算
            // (見えている位置 + スクロール量) / 全体の幅 × 曲の長さ
            const time = ((xInView + scrollLeft) / totalWidth) * wavesurfer.getDuration();

            // モーダルを開く
            openEventModal(time);
        });
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
        updateNextEventIndex();
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
        js_log(`Seeked to ${currentTime.toFixed(2)}s. Next Event Index: ${nextEventIndex}`);
    });

    // クリックやドラッグで操作した時にも次のイベントインデックスを更新する
    wavesurfer.on('interaction', () => {
         updateNextEventIndex();
         js_log("User Interaction detected, updated nextEventIndex.");
    });

    // 再生開始時に、次のイベントインデックスを更新する
    wavesurfer.on('play', () => {
        updateNextEventIndex();
        js_log("Playback started, updated nextEventIndex.");
    });


    // 一時停止した時に、正確な現在時刻を表示しなおす
    wavesurfer.on('pause', () => {
        const currentTime = wavesurfer.getCurrentTime();
        document.getElementById('time-display').textContent = currentTime.toFixed(3) + "s";
    });

    

    // 再生終了時
    wavesurfer.on('finish', () => {
        updateToggleIcon(false);
        nextEventIndex = 0; // 最初に戻す
        wavesurfer.seekTo(0);
        js_log("再生終了");
    });

    
    const activeModifiers = new Set();


    // ▼▼▼ 1. 画面全体の操作（Escで閉じる、Spaceで再生） ▼▼▼
    document.addEventListener('keydown', (e) => {

        // Escキー：最優先でモーダルを閉じる
        if (e.code === 'Escape') {
            const loading = document.getElementById('loading-overlay');
            const modal = document.getElementById('modal-event');

            // ローディングが出ていたら消す
            if (loading && loading.style.display !== 'none') {
                hideLoading();
                js_log("操作がキャンセルされました");
                e.preventDefault();
                return;
            }

            // イベント編集モーダルが出ていたら閉じる
            if (modal && modal.style.display !== 'none') {
                closeEventModal();
                e.preventDefault();
                return;
            }

            // 設定モーダルが出ていたら閉じる
            const settingsModal = document.getElementById('modal-settings');
            if (settingsModal && settingsModal.style.display !== 'none') {
                closeSettingsModal();
                e.preventDefault();
                return;
            }

            // 更新モーダルが出ていたら閉じる
            const updateModal = document.getElementById('modal-update');
            if (updateModal && updateModal.style.display !== 'none') {
                closeUpdateModal();
                e.preventDefault();
                return;
            }
        }

        // --- ここから下は、入力欄にフォーカスがある時は動かないようにする ---
        const activeTag = document.activeElement.tagName.toUpperCase();
        if (activeTag === 'INPUT' || activeTag === 'TEXTAREA' || activeTag === 'SELECT') {
            return; // 入力中はここで終了
        }

        // Spaceキー：再生/一時停止
        if (e.code === 'Space') {
            e.preventDefault(); // 画面スクロール防止
            togglePlayback();
        }
    });


    document.addEventListener('keyup', (e) => {
        // キーが離されたらセットから削除
        if (activeModifiers.has(e.code)) {
            activeModifiers.delete(e.code);
        }
    });


    // ウィンドウからフォーカスが外れたらリセット（押しっぱなし判定を防ぐ）
    window.addEventListener('blur', () => {
        activeModifiers.clear();
    });


    // ▼▼▼ 2. キー設定入力欄の操作（バッジ表示版） ▼▼▼
    const keyInputIds = ['in-key', 'modal-key'];

    keyInputIds.forEach(id => {
        const inputDiv = document.getElementById(id); // 名前を inputDiv にしましたの
        if (!inputDiv) return;

        // divなので readOnly は不要ですが、フォーカス時のスタイルはCSSでやりますの

        inputDiv.addEventListener('keydown', (e) => {
            e.preventDefault();
            e.stopPropagation();

            // 修飾キーならセットに追加
            if (['ShiftLeft', 'ShiftRight', 'ControlLeft', 'ControlRight', 'AltLeft', 'AltRight', 'MetaLeft', 'MetaRight'].includes(e.code)) {
                activeModifiers.add(e.code);
            }

            // Backspace/Delete でクリア
            if (e.code === 'Backspace' || e.code === 'Delete') {
                renderHotkeys(inputDiv, []); // 空にする
                return;
            }

            const keys = [];
            let code = e.code;

            // 1. 修飾キーそのものか判定
            const isShift = code === 'ShiftLeft' || code === 'ShiftRight';
            const isCtrl  = code === 'ControlLeft' || code === 'ControlRight';
            const isAlt   = code === 'AltLeft' || code === 'AltRight';
            const isMeta  = code === 'MetaLeft' || code === 'MetaRight';

            // 2. 修飾キーの状態チェック (追跡した Set を使って左右を判別！)
            // --- Ctrl ---
            if (e.ctrlKey && !isCtrl) {
                let added = false;
                if (activeModifiers.has('ControlLeft')) { keys.push('Left Ctrl'); added = true; }
                if (activeModifiers.has('ControlRight')) { keys.push('Right Ctrl'); added = true; }
                // フォールバック（万が一追跡漏れがあった場合）
                if (!added) keys.push('Ctrl');
            }

            // --- Alt ---
            if (e.altKey && !isAlt) {
                let added = false;
                if (activeModifiers.has('AltLeft')) { keys.push('Left Alt'); added = true; }
                if (activeModifiers.has('AltRight')) { keys.push('Right Alt'); added = true; }
                if (!added) keys.push('Alt');
            }

            // --- Shift ---
            if (e.shiftKey && !isShift) {
                let added = false;
                if (activeModifiers.has('ShiftLeft')) { keys.push('Left Shift'); added = true; }
                if (activeModifiers.has('ShiftRight')) { keys.push('Right Shift'); added = true; }
                if (!added) keys.push('Shift');
            }

            // --- Win / Meta ---
            if (e.metaKey && !isMeta) {
                 // Winキーは左右区別しないことが多いけど、一応やっておきますの
                let added = false;
                if (activeModifiers.has('MetaLeft')) { keys.push('Left Win'); added = true; }
                if (activeModifiers.has('MetaRight')) { keys.push('Right Win'); added = true; }
                if (!added) keys.push('Win'); 
            }

            // 3. メインキーの処理
            // 文字・数字キー
            if (code.startsWith('Key')) {
                code = code.replace('Key', '');
            } else if (code.startsWith('Digit')) {
                code = code.replace('Digit', '');
            } else if (code === 'Space') {
                code = 'Space';
            }
            // 修飾キー（左右区別して名前を入れる）
            else if (code === 'ShiftLeft') code = 'Left Shift';   // ★ここを 'Shift' から変更！
            else if (code === 'ShiftRight') code = 'Right Shift';
            else if (code === 'ControlLeft') code = 'Left Ctrl';  // ★ここも 'Ctrl' から変更しておいたぞ
            else if (code === 'ControlRight') code = 'Right Ctrl';
            else if (code === 'AltLeft') code = 'Left Alt';       // ★ここも
            else if (code === 'AltRight') code = 'Right Alt';
            
            // 配列に追加
            keys.push(code);

            // バッジを描画して、データとして保存
            renderHotkeys(inputDiv, keys);
        });
    });

    setUIEnabled(false); // 初期状態ではUIを無効化



    const waveformContainer = document.querySelector('#waveform');
    
    waveformContainer.addEventListener('wheel', (e) => {
        // 音声が読み込まれていないときは何もしない
        if (!wavesurfer || wavesurfer.getDuration() === 0) return;

        
        // Shiftキー + ホイール = 横スクロール
        if (e.shiftKey) {
            // コンテナがスクロール可能な状態（中身があふれている）なら
            if (waveformContainer.scrollWidth > waveformContainer.clientWidth) {
                e.preventDefault(); // ブラウザの戻る/進むなどをキャンセル
                
                // 横方向にスクロールさせる
                waveformContainer.scrollLeft += e.deltaY;
            }
        } 
        // 通常ホイール = ズーム (拡大縮小)
        else {
            e.preventDefault(); // 画面全体のスクロールを防止

            // ズーム感度
            const zoomDelta = e.deltaY > 0 ? -10 : 10; 
            
            currentZoom += zoomDelta;
            
            // 範囲制限 (0 = 全体表示, 500 = かなり拡大)
            if (currentZoom < 0) currentZoom = 0;
            if (currentZoom > 500) currentZoom = 500;
            
            wavesurfer.zoom(currentZoom);

        }
    }, { passive: false }); // preventDefaultを使うために passive: false が必須！
});

// UIの有効/無効を切り替える関数
function setUIEnabled(enabled) {
    // 1. ボタン類の disabled 属性切り替え
    const idsToDisable = ['btn-save', 'btn-add', 'in-time', 'in-type', 'in-key', 'btn-skip-back', 'btn-skip-fwd'];
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

function clearLog() {
    const box = document.getElementById('log-box');
    if (box) {
        box.innerHTML = '';
        // クリアしたことをログに残すという矛盾...でもわかりやすいですの
        // js_log("ログをクリアしましたの"); 
    }
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
        <span>${escapeHtml(msg)}</span>
    `;
    
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
}

// ★ 1. Pythonから呼ばれる関数を定義して公開（expose）
eel.expose(set_update_progress_js);
function set_update_progress_js(percent, message) {
    const bar = document.getElementById('update-progress-bar');
    const text = document.getElementById('update-progress-text');
    const detail = document.getElementById('update-status-detail');

    // バーの幅を更新
    if (percent >= 0) {
        bar.style.width = percent + "%";
        text.innerText = percent + "%";
    }
    
    // メッセージがあれば更新
    if (message) {
        detail.innerText = message;
    }
}


eel.expose(close_window_js);
function close_window_js() {
    window.close();
}

// --- UI操作 ---

async function executeUpdate() {
    if (!pendingUpdateUrl) return;

    const btn = document.getElementById('btn-do-update');
    const msgEl = document.getElementById('update-message');
    const progressArea = document.getElementById('update-progress-area'); // 追加
    
    if (!confirm("アプリを更新して再起動します。\nよろしいですか？")) {
        return;
    }

    // UIを更新モードに切り替え
    btn.disabled = true;
    btn.style.display = 'none'; // ボタンを消す
    const cancelBtn = document.querySelector('#modal-update .btn-cancel');
    if (cancelBtn) cancelBtn.style.display = 'none'; // 閉じるボタンも消す（中断不可）

    msgEl.innerText = "更新を実行中ですの...";

    if (progressArea) {
        progressArea.style.display = 'block';
    }

    try {
        const result = await eel.perform_update(pendingUpdateUrl)();
        if (result === false) {
            msgEl.innerText = "更新に失敗しました";
            btn.disabled = false;
            btn.style.display = 'block';
            if (cancelBtn) cancelBtn.style.display = '';
        }
    } catch (e) {
        js_log("更新エラー: " + e);
        msgEl.innerText = "更新に失敗しました";
        btn.disabled = false;
        btn.style.display = 'block';
        if (cancelBtn) cancelBtn.style.display = '';
    }
}

async function pickAudio() {

    showLoading();

    // Python 側から { full_path, rel_path } を含むオブジェクトが返る想定
    let data = await eel.select_audio_file()();
    
    if (data) {
        const statusEl = document.getElementById('audio-status');
        const fileName = data.full_path.split('\\').pop().split('/').pop();


        statusEl.textContent = fileName;
        statusEl.title = data.full_path; // ホバーでフルパス表示
        statusEl.classList.add('active'); // 色を緑にする

        // 見えないところにフルパスを保持しておく（保存時に必要！）
        statusEl.dataset.fullPath = data.full_path;
        
        loadWaveform(data.rel_path);
        js_log("Audio Selected: " + data.full_path);
        
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
        const statusEl = document.getElementById('audio-status');
        const fileName = data.audio_name || data.audio_path.split('\\').pop().split('/').pop();
        
        statusEl.textContent = fileName;
        statusEl.title = data.audio_path;
        statusEl.classList.add('active');
        statusEl.dataset.fullPath = data.audio_path;

        events = Array.isArray(data.events)
            ? data.events
                .filter(e => e && typeof e === 'object')
                .map(e => {
                    const eventType = e.type === 'pause' ? 'pause' : 'press';
                    return {
                        time: parseFloat(e.time),
                        type: eventType,
                        key: eventType === 'pause' ? '' : String(e.key || '')
                    };
                })
                .filter(e => Number.isFinite(e.time))
            : [];
        renderEvents();
        js_log("Bundle Loaded");

        if (data.rel_path) {
            loadWaveform(data.rel_path);
        } else {
            hideLoading();
            setUIEnabled(true);
        }
    } else {
        hideLoading();
    }
}

// イベントを追加する
function addEvent() {
    const t = document.getElementById('in-time').value;
    const type = document.getElementById('in-type').value;

    const keyDiv = document.getElementById('in-key');
    const key = keyDiv.dataset.value || ''; // 値がない時は空文字

    if (!t) return;
    
    events.push({
        time: parseFloat(t),
        type: type,
        key: type === 'pause' ? '' : key
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

        // ▼▼▼ 1. Typeをバッジにする処理 ▼▼▼
        // 'press' か 'pause' かでクラスを分ける
        const typeClass = ev.type === 'pause' ? 'pause' : 'press';
        // HTMLを作成
        const typeHTML = `<span class="type-badge ${typeClass}">${escapeHtml(ev.type || '')}</span>`;
        
        // ▼▼▼ 2. Keyをバッジにする処理（さっきのまま） ▼▼▼
        let keyHTML = '-';
        if (ev.key) {
            // "Ctrl+Shift+A" を分解して spanタグの連なりにする
            keyHTML = String(ev.key).split('+').map(k => {
                let cls = 'kbd-badge';
                // 色分けクラスの付与
                const lower = k.toLowerCase();
                if (lower.includes('ctrl')) cls += ' ctrl';
                if (lower.includes('shift')) cls += ' shift';
                if (lower.includes('alt')) cls += ' alt';
                
                return `<span class="${cls}">${escapeHtml(k)}</span>`;
            }).join(''); // 文字列として結合
        }

        row.innerHTML = `
            <div>${ev.time.toFixed(3)}</div>
            <div>${typeHTML}</div>
            <div>${keyHTML}</div>
            <div><button onclick="deleteEvent(${idx})" style="padding:2px 5px; background: #d33;">×</button></div>
        `;
        container.appendChild(row);
    });
    renderMarkers();
}

// 選択したタイプに応じてキー入力欄の表示/非表示を切り替える
function toggleInput() {
    const type = document.getElementById('in-type').value;
    const keyInput = document.getElementById('in-key');
    if (type === 'pause') {
        keyInput.style.display = 'none';
    } else {
        keyInput.style.display = 'flex';
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
    // 表示テキストではなく、datasetからフルパスを取得する
    const statusEl = document.getElementById('audio-status');
    const fullPath = statusEl.dataset.fullPath;

    if (!fullPath) {
        js_log("エラー: 音声ファイルが選択されていません");
        return;
    }

    const data = {
        audio_file: fullPath, // ここでフルパスを使う
        events: events
    };
    await eel.save_bundle(JSON.stringify(data))();
}


function loadWaveform(url) {
    // WaveSurfer にオーディオを読み込ませる
    wavesurfer.load(url);
}

// ▼▼▼ スキップ機能 ▼▼▼

function skipBackward() {
    if (!wavesurfer) return;
    // 設定値を使う
    wavesurfer.skip(-appConfig.skipSeconds);
    updateNextEventIndex();
    js_log(`skipped back ${appConfig.skipSeconds}s`);
}

function skipForward() {
    if (!wavesurfer) return;
    // 設定値を使う
    wavesurfer.skip(appConfig.skipSeconds);
    updateNextEventIndex();
    js_log(`skipped forward ${appConfig.skipSeconds}s`);
}


// ★ バッジを描画するヘルパー関数 ★
function renderHotkeys(element, keyArray) {
    // 1. まず中身をリセット
    element.innerHTML = '';

    keyArray.forEach(k => {
        const span = document.createElement('span');
        span.className = 'kbd-badge';
        
        const lower = k.toLowerCase();

        // --- 色付けのクラス付与 ---
        if (lower.includes('ctrl')) span.classList.add('ctrl');
        if (lower.includes('shift')) span.classList.add('shift');
        if (lower.includes('alt')) span.classList.add('alt');
        
        // --- 表示テキストの調整 ---
        // 内部データは "Right Shift" だが、画面には "R-Shift" と出す
        let displayText = k;
        
        if (lower.includes('right')) {
            span.classList.add('right-key'); // 必要ならCSSで右専用の色を作れるようにクラス追加
            displayText = k.replace('Right ', 'R-'); // "Right Shift" → "R-Shift"
        } 
        else if (lower.includes('left')) {
            span.classList.add('left-key'); // 必要ならCSSで左専用の色を作れるようにクラス追加
            displayText = k.replace('Left ', 'L-'); // "Left Shift" → "L-Shift"
        }        // それ以外はそのまま

        span.textContent = displayText;
        element.appendChild(span);
    });

    // 2. 実際の値は「完全な文字列」で保存 (Pythonには "Right Shift" と送るため)
    element.dataset.value = keyArray.join('+');
}


// ▼▼▼ モーダル関連の関数 ▼▼▼

function openEventModal(time) {


    if (wavesurfer && wavesurfer.isPlaying()) {
        wavesurfer.pause();
        updateToggleIcon(false); // アイコンを「再生」に戻す
        js_log("再生を一時停止(Open Modal)");
    }


    const modal = document.getElementById('modal-event');
    const timeInput = document.getElementById('modal-time');

    const keyDiv = document.getElementById('modal-key');
    renderHotkeys(keyDiv, []); // ★空にする
    
    // 時間をセット
    timeInput.value = time.toFixed(3);
        
    // 表示
    modal.style.display = 'flex';
    
    // 少し待ってからフォーカスしないと効かないことがある
    setTimeout(() => keyDiv.focus(), 50);
}

function closeEventModal() {
    document.getElementById('modal-event').style.display = 'none';
}

function toggleModalInput() {
    const type = document.getElementById('modal-type').value;
    const keyDiv = document.getElementById('modal-key');

    if (type === 'pause') {
        // divは .disabled が効かないので、CSSで操作を封じますの
        keyDiv.style.pointerEvents = 'none'; // クリックやキー入力を無効化
        keyDiv.style.opacity = 0.5;          // 薄くする
        keyDiv.setAttribute('data-placeholder', '一時停止'); // プレースホルダー文言変更
        renderHotkeys(keyDiv, []);           // 中身を空にする
    } else {
        keyDiv.style.pointerEvents = 'auto'; // 操作を許可
        keyDiv.style.opacity = 1;
        keyDiv.setAttribute('data-placeholder', 'キーを押してください...');
        keyDiv.focus();
    }
}

function saveEventFromModal() {
    const timeVal = document.getElementById('modal-time').value;
    const typeVal = document.getElementById('modal-type').value;

    const keyDiv = document.getElementById('modal-key');
    const keyVal = keyDiv.dataset.value || '';

    if (!timeVal) return;

    // イベント追加
    events.push({
        time: parseFloat(timeVal),
        type: typeVal,
        key: typeVal === 'pause' ? '' : keyVal
    });
    
    // ソートして再描画
    events.sort((a, b) => a.time - b.time);
    renderEvents();
    
    closeEventModal();
    js_log(`イベントを追加しました: ${timeVal}s (${typeVal})`);
}

// モーダルの背景をクリックしたら閉じる処理（お好みで）
document.getElementById('modal-event').addEventListener('click', (e) => {
    if (e.target.id === 'modal-event') {
        closeEventModal();
    }
});


// ▼▼▼ 波形上にマーカー（フラグ）を描画する関数 ▼▼▼
function renderMarkers() {
    if (!wsRegions) return;

    // 一旦すべてのマーカーを消す（重複防止）
    wsRegions.clearRegions();

    events.forEach(ev => {
        // タイプによって色を変える（キー＝青系、一時停止＝赤系）
        // alpha(透明度)を0.5くらいにして透けさせると綺麗ですの
        const color = ev.type === 'pause' 
            ? 'rgba(243, 139, 168, 0.5)'  // 赤
            : 'rgba(137, 180, 250, 0.5)'; // 青

        wsRegions.addRegion({
            start: ev.time,
            end: ev.time, // startとendを同じにすると「線」になりますの
            color: color,
            content: ev.type === 'pause' ? 'II' : ev.key, // ラベルを表示
            drag: false,   // 勝手に動かせないように固定
            resize: false, // サイズ変更も禁止
        });
    });
}


function openSettingsModal() {
    // 1. 現在の設定値をUI（入力欄）にセットする
    document.getElementById('set-duration').value = appConfig.keyDuration;
    document.getElementById('val-duration').innerText = appConfig.keyDuration.toFixed(2) + "s";

    document.getElementById('set-skip').value = appConfig.skipSeconds;

    document.getElementById('set-volume').value = appConfig.volume;
    document.getElementById('val-volume').innerText = Math.round(appConfig.volume * 100) + "%";

    document.getElementById('set-autoscroll').checked = appConfig.autoScroll;

    // 2. 再生中なら一時停止する
    if (wavesurfer && wavesurfer.isPlaying()) {
        wavesurfer.pause();
        updateToggleIcon(false);
    }
    
    // 3. モーダルを表示
    document.getElementById('modal-settings').style.display = 'flex';
}




function closeSettingsModal() {
    document.getElementById('modal-settings').style.display = 'none';
}


function loadSettings() {
    const saved = localStorage.getItem('vts_player_config');
    if (saved) {
        try {
            const parsed = JSON.parse(saved);
            // 既存の設定オブジェクトに上書き（新しい設定項目が増えても大丈夫なように）
            appConfig = { ...appConfig, ...parsed };
        } catch (e) {
            console.error("設定の読み込みに失敗:", e);
        }
    }
    // Python側にも初期値を送っておく
    eel.update_key_duration_py(appConfig.keyDuration);
}


function saveSettings() {
    localStorage.setItem('vts_player_config', JSON.stringify(appConfig));
}

// UIの入力変更時に呼ばれる関数
function updateSettings(key) {
    if (!wavesurfer) return;

    if (key === 'duration') {
        const val = parseFloat(document.getElementById('set-duration').value);
        appConfig.keyDuration = val;
        document.getElementById('val-duration').innerText = val.toFixed(2) + "s";
        // Pythonに通知
        eel.update_key_duration_py(val);
    }
    else if (key === 'skip') {
        const val = parseInt(document.getElementById('set-skip').value);
        appConfig.skipSeconds = val;
    }
    else if (key === 'volume') {
        const val = parseFloat(document.getElementById('set-volume').value);
        appConfig.volume = val;
        document.getElementById('val-volume').innerText = Math.round(val * 100) + "%";
        // 即時反映
        wavesurfer.setVolume(val);
    }
    else if (key === 'autoscroll') {
        const val = document.getElementById('set-autoscroll').checked;
        appConfig.autoScroll = val;
        // 即時反映 (v7のsetOptionsを使用)
        wavesurfer.setOptions({ autoCenter: val });
    }
    // 変更があるたびに保存
    saveSettings();
}


// 設定モーダルの背景クリックで閉じる
document.getElementById('modal-settings').addEventListener('click', (e) => {
    if (e.target.id === 'modal-settings') {
        closeSettingsModal();
    }
});


// --- アップデート関連 ---

let pendingUpdateUrl = ""; // 更新用URLを一時保存する場所

// 1. 更新チェックボタンが押されたら呼ばれる関数
// main.js の checkUpdate 関数

async function checkUpdate(isAuto = false) {
    const modal = document.getElementById('modal-update');    
    const msgEl = document.getElementById('update-message');
    const curVerEl = document.getElementById('disp-current-ver');
    const latVerEl = document.getElementById('disp-latest-ver');
    const arrowEl = document.getElementById('version-arrow');
    const logEl = document.getElementById('update-changelog');
    const btnUpdate = document.getElementById('btn-do-update');
    
    // SVGアイコンの定義（見やすいようにサイズは24pxにしましたの）
    const SVG_ARROW = `
        <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="5" y1="12" x2="19" y2="12"></line>
            <polyline points="12 5 19 12 12 19"></polyline>
        </svg>`;
        
    const SVG_EQUAL = `
        <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="5" y1="9" x2="19" y2="9"></line>
            <line x1="5" y1="15" x2="19" y2="15"></line>
        </svg>`;

if (!isAuto) {
        modal.style.display = 'flex';
        msgEl.innerText = "GitHubを確認しています...";
        msgEl.style.color = "#ccc";
        
        curVerEl.innerText = "-";
        latVerEl.innerText = "-";
        latVerEl.style.color = "#888";
        
        arrowEl.style.display = 'none';
        arrowEl.innerHTML = ""; 

        logEl.style.display = 'none';
        logEl.innerText = "";
        btnUpdate.style.display = 'none';
    }
    
    pendingUpdateUrl = "";

    // --- Pythonへ問い合わせ ---
    let result = await eel.check_for_updates()();

    // 結果判定
    if (result.error) {
        // 自動チェックでエラーなら何もしない（裏で失敗するだけ）
        if (isAuto) return;

        msgEl.innerText = "エラーが発生しました";
        msgEl.style.color = "#f38ba8";
        latVerEl.innerText = "Error";
        return;
    }

    // ここで初めて、自動チェックでも「更新があるなら」モーダルを表示する準備をする
    if (isAuto && !result.update_available) {
        // 自動チェックかつ更新なし → 何もせず終了
        return;
    }

    // ここまで来たらモーダルを表示（自動チェックで更新あり、または手動チェック）
    modal.style.display = 'flex'; 

    curVerEl.innerText = result.current_version;

    // 真ん中の記号を表示
    arrowEl.style.display = 'flex';
    arrowEl.style.alignItems = 'center';
    arrowEl.style.justifyContent = 'center';

    if (result.update_available) {
        // ★更新がある場合
        msgEl.innerText = "新しいバージョンがあります！";
        msgEl.style.color = "#a6e3a1"; // 緑

        latVerEl.innerText = result.latest_version;
        latVerEl.style.color = "#a6e3a1"; 

        arrowEl.innerHTML = SVG_ARROW;
        arrowEl.style.color = "#89b4fa"; 

        logEl.innerText = result.body;
        logEl.style.display = 'block';

        if (result.download_url) {
            pendingUpdateUrl = result.download_url;
            btnUpdate.style.display = 'block';
        }

    } else if (result.is_dev_version) {
        // ★現在バージョンの方が新しい場合（開発版）
        msgEl.innerText = "（これは開発中のバージョンです）";
        msgEl.style.color = "#fab387"; // オレンジ色で注意喚起っぽく

        latVerEl.innerText = result.latest_version;
        latVerEl.style.color = "#888"; // 最新版は「過去」なので少し暗く

        // 逆矢印とか、Devっぽいアイコンにしてもいいけど、とりあえず "←" にしますの
        arrowEl.innerHTML = `
        <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="19" y1="12" x2="5" y2="12"></line>
            <polyline points="12 19 5 12 12 5"></polyline>
        </svg>`;
        arrowEl.style.color = "#fab387"; 

        logEl.innerText = "GitHub上の最新リリースよりも先のバージョンを使っています。\nバグに気をつけてください。";
        logEl.style.display = 'block';
        
        // 更新ボタンは出さない
        btnUpdate.style.display = 'none';

    } else {
        // ★最新の場合（手動チェックの時のみここに来る）
        msgEl.innerText = "現在は最新版です";
        msgEl.style.color = "#89b4fa"; // 青

        latVerEl.innerText = result.current_version; 
        latVerEl.style.color = "#89b4fa"; 
        
        arrowEl.innerHTML = SVG_EQUAL;
        arrowEl.style.color = "#666"; 
    }
}


// ログ出力用ヘルパー（既存のログ機能を使う前提）
function logToDiv(msg) {
    // もし既存のログ関数があればそれを使ってくださいですの
    // なければコンソールへ
    if (window.eel && window.eel.js_log) {
        // Pythonからの呼び出し用関数があるなら何もしない（循環するから）
        // ここでは単純に画面に表示するロジックを書くか、console.log
        console.log(msg);
        // 簡易的にログボックスへ追記する場合:
        const logBox = document.getElementById('log-box');
        if(logBox) {
            const div = document.createElement('div');
            div.textContent = `[System] ${msg}`;
            logBox.appendChild(div);
            logBox.scrollTop = logBox.scrollHeight;
        }
    }
}


async function initVersion() {
    // Pythonの get_version() を呼ぶ
    let ver = await eel.get_version()();
    
    // HTMLの要素にセット
    let label = document.getElementById('version-label');
    if (label) {
        label.innerText = ver;
    }
}

// ▼▼▼ アップデートモーダルを閉じる関数（これを追加するのですの！） ▼▼▼
function closeUpdateModal() {
    document.getElementById('modal-update').style.display = 'none';
}

// （おまけ）モーダルの背景（黒い部分）をクリックしても閉じられるようにしておくと便利ですの
document.getElementById('modal-update').addEventListener('click', (e) => {
    if (e.target.id === 'modal-update') {
        closeUpdateModal();
    }
});
