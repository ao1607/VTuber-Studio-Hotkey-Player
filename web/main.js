let events = [];
let totalDuration = 0;
let wavesurfer = null; // 波形表示用の WaveSurfer インスタンス
let wsRegions = null; // WaveSurfer Regions プラグインインスタンス

// 再生状態管理フラグ
let isPlaying = false; // 再生中かどうかのフラグ
let isPaused = false;  // 一時停止中かどうかのフラグ
let pausedAt = 0;    // 一時停止した時刻（再開時に使用）
let nextEventIndex = 0; // 次に発火すべきイベントのインデックス


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

    document.addEventListener('contextmenu', (e) => {
        e.preventDefault();
    });

    // WaveSurferの初期化
    wavesurfer = WaveSurfer.create({
        container: '#waveform',
        waveColor: '#4d4d60',      // 波形の色（未再生）
        progressColor: '#89b4fa',  // 波形の色（再生済み）
        cursorColor: '#ff5555',    // カーソルの色
        height: 90,
        responsive: true,
        normalize: true,           // 波形を最大化して見やすく
        backend: 'WebAudio',
        minPxPerSec: 0, // 最初は全体表示
        autoCenter: false, // 勝手にスクロールされると邪魔なのでOFF
        dragToSeek: true,  // クリック＆ドラッグでシーク可能に

        plugins: [
            WaveSurfer.Regions.create() // ここで有効化！
        ],
    });

    wsRegions = wavesurfer.plugins[0];

    wavesurfer.setVolume(1.0); // 音量を 1.0 に設定
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
            if (settingsModal && settingsModal.style.display !== 'none') {
                closeSettingsModal();
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


    // ▼▼▼ 2. キー設定入力欄の操作（バッジ表示版） ▼▼▼
    const keyInputIds = ['in-key', 'modal-key'];

    keyInputIds.forEach(id => {
        const inputDiv = document.getElementById(id); // 名前を inputDiv にしましたの
        if (!inputDiv) return;

        // divなので readOnly は不要ですが、フォーカス時のスタイルはCSSでやりますの

        inputDiv.addEventListener('keydown', (e) => {
            e.preventDefault();
            e.stopPropagation();

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

            // 2. 修飾キーの状態チェック (押されているものを追加)
            if (e.ctrlKey && !isCtrl) keys.push('Ctrl');
            if (e.altKey && !isAlt) keys.push('Alt');
            if (e.shiftKey && !isShift) keys.push('Shift');
            if (e.metaKey && !isMeta) keys.push('Win'); 

            // 3. メインキーの処理
            // 文字・数字キー
            if (code.startsWith('Key')) {
                code = code.replace('Key', '');
            } else if (code.startsWith('Digit')) {
                code = code.replace('Digit', '');
            } else if (code === 'Space') {
                code = 'Space';
            }
            // 修飾キー（左右区別）
            else if (code === 'ShiftLeft') code = 'Shift';
            else if (code === 'ShiftRight') code = 'Right Shift';
            else if (code === 'ControlLeft') code = 'Ctrl';
            else if (code === 'ControlRight') code = 'Right Ctrl';
            else if (code === 'AltLeft') code = 'Alt';
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
        const fileName = data.audio_path.split('\\').pop().split('/').pop();
        
        statusEl.textContent = fileName;
        statusEl.title = data.audio_path;
        statusEl.classList.add('active');
        statusEl.dataset.fullPath = data.audio_path;

        events = data.events;
        events.forEach(e => e.time = parseFloat(e.time));
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

        // ▼▼▼ 1. Typeをバッジにする処理 ▼▼▼
        // 'press' か 'pause' かでクラスを分ける
        const typeClass = ev.type === 'pause' ? 'pause' : 'press';
        // HTMLを作成
        const typeHTML = `<span class="type-badge ${typeClass}">${ev.type}</span>`;
        
        // ▼▼▼ 2. Keyをバッジにする処理（さっきのまま） ▼▼▼
        let keyHTML = '-';
        if (ev.key) {
            // "Ctrl+Shift+A" を分解して spanタグの連なりにする
            keyHTML = ev.key.split('+').map(k => {
                let cls = 'kbd-badge';
                // 色分けクラスの付与
                const lower = k.toLowerCase();
                if (lower.includes('ctrl')) cls += ' ctrl';
                if (lower.includes('shift')) cls += ' shift';
                if (lower.includes('alt')) cls += ' alt';
                
                return `<span class="${cls}">${k}</span>`;
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
    // 現在位置から -10秒
    wavesurfer.skip(-10);
    updateNextEventIndex(); // スキップ後に次のイベントを更新
    js_log("skipped back 10s");
}

function skipForward() {
    if (!wavesurfer) return;
    // 現在位置から +10秒
    wavesurfer.skip(10);
    updateNextEventIndex(); // スキップ後に次のイベントを更新
    js_log("skipped forward 10s");
}


// ★ バッジを描画するヘルパー関数 ★
function renderHotkeys(element, keyArray) {
    // 1. 見た目を作る (HTML)
    element.innerHTML = '';
    keyArray.forEach(k => {
        const span = document.createElement('span');
        span.className = 'kbd-badge';
        
        // クラスをつけて色を変える（小文字にして判定）
        if (k.toLowerCase().includes('ctrl')) span.classList.add('ctrl');
        if (k.toLowerCase().includes('shift')) span.classList.add('shift');
        if (k.toLowerCase().includes('alt')) span.classList.add('alt');
        
        span.textContent = k;
        element.appendChild(span);
    });

    // 2. 実際の値をデータ属性に保存 (JSで読み取る用)
    // 例: data-value="Ctrl+Shift+A"
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
        keyDiv.setAttribute('data-placeholder', 'キーを押すのですの');
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
    // 再生中なら止める（お好みで）
    if (wavesurfer && wavesurfer.isPlaying()) {
        wavesurfer.pause();
        updateToggleIcon(false);
    }
    
    document.getElementById('modal-settings').style.display = 'flex';
}

function closeSettingsModal() {
    document.getElementById('modal-settings').style.display = 'none';
}

// 設定モーダルの背景クリックで閉じる
document.getElementById('modal-settings').addEventListener('click', (e) => {
    if (e.target.id === 'modal-settings') {
        closeSettingsModal();
    }
});