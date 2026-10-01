// リハ・アシスト - 毎日のリハビリ音声ガイド

let config = null;
let currentQueue = []; // トラックIDのキュー
let currentQueueIndex = 0;
let timelines = {};    // キャッシュされたタイムラインデータ

// DOM要素
const audio = document.getElementById("audioPlayer");
const statusBadge = document.getElementById("statusBadge");
const courseStepBadge = document.getElementById("courseStepBadge");
const currentTrackTitle = document.getElementById("currentTrackTitle");
const currentPhaseName = document.getElementById("currentPhaseName");
const guideCircle = document.getElementById("guideCircle");
const guideActionText = document.getElementById("guideActionText");
const guideCountdown = document.getElementById("guideCountdown");
const speechCaption = document.getElementById("speechCaption");
const currentTimeDisplay = document.getElementById("currentTimeDisplay");
const totalTimeDisplay = document.getElementById("totalTimeDisplay");
const progressBarContainer = document.getElementById("progressBarContainer");
const progressBarFill = document.getElementById("progressBarFill");

const btnPlayPause = document.getElementById("btnPlayPause");
const playPauseIcon = document.getElementById("playPauseIcon");
const playPauseLabel = document.getElementById("playPauseLabel");
const btnRestart = document.getElementById("btnRestart");
const btnNext = document.getElementById("btnNext");

const todayWeekdayBadge = document.getElementById("todayWeekdayBadge");
const recommendDayText = document.getElementById("recommendDayText");
const recommendTimeText = document.getElementById("recommendTimeText");
const recommendCourseTitle = document.getElementById("recommendCourseTitle");
const recommendCourseDesc = document.getElementById("recommendCourseDesc");
const btnStartToday = document.getElementById("btnStartToday");
const courseListGrid = document.getElementById("courseListGrid");
const trackListGrid = document.getElementById("trackListGrid");

// 時間フォーマット (00:00)
function formatTime(seconds) {
  if (isNaN(seconds)) return "00:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

// 設定JSON読み込み
async function loadConfig() {
  try {
    const res = await fetch("rehab_config.json");
    config = await res.json();
    initApp();
  } catch (err) {
    console.error("設定ファイルの読み込みに失敗しました:", err);
  }
}

// アプリの初期化
function initApp() {
  setupTodayRecommendation();
  renderCourseList();
  renderTrackList();
  registerServiceWorker();

  // 初期トラック設定（おすすめコースの1曲目）
  const day = new Date().getDay().toString();
  const schedule = config.weekdaySchedule[day] || config.weekdaySchedule["1"];
  const initialCourse = config.courses.find(c => c.id === schedule.courseId) || config.courses[0];
  setupQueue(initialCourse.tracks, false);
}

// 曜日別おすすめのUI構築
function setupTodayRecommendation() {
  const day = new Date().getDay().toString();
  const schedule = config.weekdaySchedule[day] || config.weekdaySchedule["1"];
  const course = config.courses.find(c => c.id === schedule.courseId) || config.courses[0];

  todayWeekdayBadge.textContent = `${schedule.dayName}のおすすめ`;
  recommendDayText.textContent = `${schedule.dayName}：${schedule.theme}`;
  recommendTimeText.textContent = course.timeLabel;
  recommendCourseTitle.textContent = course.name;
  recommendCourseDesc.textContent = schedule.message;

  btnStartToday.onclick = () => {
    setupQueue(course.tracks, true);
    scrollToPlayer();
  };
}

// コース一覧のレンダリング
function renderCourseList() {
  courseListGrid.innerHTML = "";
  config.courses.forEach(course => {
    const card = document.createElement("div");
    card.className = "course-card";
    card.innerHTML = `
      <div class="course-card-icon">${course.icon}</div>
      <div class="course-card-body">
        <div class="course-card-top">
          <span class="course-card-title">${course.name}</span>
          <span class="course-card-time">${course.timeLabel}</span>
        </div>
        <div class="course-card-desc">${course.description}</div>
      </div>
    `;
    card.onclick = () => {
      setupQueue(course.tracks, true);
      highlightActiveCard(card, ".course-card");
      scrollToPlayer();
    };
    courseListGrid.appendChild(card);
  });
}

// 個別メニュー一覧のレンダリング
function renderTrackList() {
  trackListGrid.innerHTML = "";
  Object.values(config.tracks).forEach(track => {
    const card = document.createElement("div");
    card.className = "menu-card";
    card.setAttribute("data-track-id", track.id);
    card.innerHTML = `
      <div class="menu-icon">${track.icon}</div>
      <div class="menu-details">
        <h4>${track.title}</h4>
        <p>${track.subtitle}</p>
        <span class="menu-duration">${track.durationLabel}</span>
      </div>
    `;
    card.onclick = () => {
      setupQueue([track.id], true);
      highlightActiveCard(card, ".menu-card");
      scrollToPlayer();
    };
    trackListGrid.appendChild(card);
  });
}

function highlightActiveCard(targetCard, selector) {
  document.querySelectorAll(selector).forEach(c => c.classList.remove("active"));
  if (targetCard) targetCard.classList.add("active");
}

function scrollToPlayer() {
  const card = document.getElementById("playerCard");
  if (card) {
    card.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

// キューのセットアップ
function setupQueue(trackIds, autoPlay = true) {
  currentQueue = [...trackIds];
  currentQueueIndex = 0;
  loadQueueItem(currentQueueIndex, autoPlay);
}

// 指定インデックスのトラック読み込み
async function loadQueueItem(index, autoPlay = false) {
  if (index < 0 || index >= currentQueue.length) return;
  currentQueueIndex = index;
  const trackId = currentQueue[currentQueueIndex];
  const track = config.tracks[trackId];

  // ステップ表示
  if (currentQueue.length > 1) {
    courseStepBadge.style.display = "inline-block";
    courseStepBadge.textContent = `${index + 1} / ${currentQueue.length}`;
  } else {
    courseStepBadge.style.display = "none";
  }

  // 表示リセット
  currentTrackTitle.textContent = track.title;
  currentPhaseName.textContent = "準備中";
  guideActionText.textContent = "待機中";
  guideCountdown.textContent = "--";
  guideCircle.className = "guide-circle";
  speechCaption.textContent = "「スタートボタンを押して開始してください」";

  // 音声読み込み
  audio.src = track.audioSrc;
  audio.load();

  // タイムライン読み込み
  await loadTimeline(track);

  // ロック画面・バックグラウンドメディア情報更新
  updateMediaSession(track);

  if (autoPlay) {
    playAudio();
  } else {
    updatePlayButton(false);
  }
}

let wakeLock = null;

// 画面スリープ防止（Wake Lock）
async function requestWakeLock() {
  if ('wakeLock' in navigator) {
    try {
      wakeLock = await navigator.wakeLock.request('screen');
      wakeLock.addEventListener('release', () => {
        wakeLock = null;
      });
    } catch (err) {
      console.log('Wake Lock request:', err);
    }
  }
}

function releaseWakeLock() {
  if (wakeLock) {
    wakeLock.release().catch(() => {});
    wakeLock = null;
  }
}

// 画面復帰時のスリープ防止再設定
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && !audio.paused) {
    requestWakeLock();
  }
});

// スマホのロック画面・バックグラウンド再生メタデータ
function updateMediaSession(track) {
  if ('mediaSession' in navigator) {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: track.title,
      artist: "リハ・アシスト（声・腕・足）",
      album: "まいにちリハビリ",
      artwork: [
        { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
        { src: 'icon-512.png', sizes: '512x512', type: 'image/png' }
      ]
    });

    navigator.mediaSession.setActionHandler('play', () => playAudio());
    navigator.mediaSession.setActionHandler('pause', () => pauseAudio());
    navigator.mediaSession.setActionHandler('previoustrack', () => {
      if (currentQueueIndex > 0) loadQueueItem(currentQueueIndex - 1, true);
    });
    navigator.mediaSession.setActionHandler('nexttrack', () => {
      if (currentQueueIndex + 1 < currentQueue.length) loadQueueItem(currentQueueIndex + 1, true);
    });
  }
}

// タイムラインデータ読み込み
async function loadTimeline(track) {
  if (timelines[track.id]) return timelines[track.id];
  try {
    const res = await fetch(track.timelineSrc);
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    const data = await res.json();
    timelines[track.id] = data;
    return data;
  } catch (err) {
    console.warn(`タイムライン読込スキップ: ${track.id}`, err);
    return null;
  }
}

// 再生・一時停止制御
function togglePlayPause() {
  if (audio.paused) {
    playAudio();
  } else {
    pauseAudio();
  }
}

function playAudio() {
  requestWakeLock();
  audio.play().then(() => {
    updatePlayButton(true);
    statusBadge.textContent = currentQueue.length > 1 ? "コース進行中" : "再生中";
    statusBadge.className = "status-badge active";
  }).catch(err => {
    console.error("音声再生エラー:", err);
  });
}

function pauseAudio() {
  audio.pause();
  releaseWakeLock();
  updatePlayButton(false);
  statusBadge.textContent = "一時停止中";
  statusBadge.className = "status-badge pause";
  guideCircle.className = "guide-circle";
}

function updatePlayButton(isPlaying) {
  if (isPlaying) {
    playPauseIcon.textContent = "⏸";
    playPauseLabel.textContent = "一時停止";
    btnPlayPause.style.background = "#d97706";
    btnPlayPause.style.borderColor = "#b45309";
  } else {
    playPauseIcon.textContent = "▶";
    playPauseLabel.textContent = "スタート";
    btnPlayPause.style.background = "#0284c7";
    btnPlayPause.style.borderColor = "#0369a1";
  }
}

// 再生時間同期イベント
audio.addEventListener("timeupdate", () => {
  const current = audio.currentTime;
  const total = audio.duration || 0;

  currentTimeDisplay.textContent = formatTime(current);
  totalTimeDisplay.textContent = `/ ${formatTime(total)}`;

  if (total > 0) {
    const pct = (current / total) * 100;
    progressBarFill.style.width = `${pct}%`;
  }

  const trackId = currentQueue[currentQueueIndex];
  const tData = timelines[trackId];
  if (!tData || !tData.timeline) return;

  let activeItem = null;
  let activeSection = null;

  for (const it of tData.timeline) {
    if (it.type === "section" && current >= it.start) {
      activeSection = it.title;
    }
    if ((it.type === "speech" || it.type === "silence") && current >= it.start && current <= it.end) {
      activeItem = it;
    }
  }

  if (activeSection) {
    currentPhaseName.textContent = activeSection;
  }

  if (activeItem) {
    const remaining = Math.max(0, Math.ceil(activeItem.end - current));

    if (activeItem.type === "speech") {
      speechCaption.textContent = `「${activeItem.text}」`;
      const txt = activeItem.text;
      if (txt.includes("吸って") || txt.includes("吸い")) {
        guideCircle.className = "guide-circle inhale";
        guideActionText.textContent = "吸う";
        guideCountdown.textContent = remaining > 0 ? remaining : "";
      } else if (txt.includes("止め") || txt.includes("保ち") || txt.includes("キープ")) {
        guideCircle.className = "guide-circle hold";
        guideActionText.textContent = "保つ";
        guideCountdown.textContent = remaining > 0 ? remaining : "";
      } else if (txt.includes("吐") || txt.includes("ふう")) {
        guideCircle.className = "guide-circle exhale";
        guideActionText.textContent = "吐く";
        guideCountdown.textContent = remaining > 0 ? remaining : "";
      } else {
        guideCircle.className = "guide-circle";
        guideActionText.textContent = "案内中";
        guideCountdown.textContent = "";
      }
    } else if (activeItem.type === "silence") {
      const secName = activeItem.section || "";
      if (secName.includes("インターバル") || secName.includes("休息") || activeItem.duration >= 10) {
        guideCircle.className = "guide-circle rest";
        guideActionText.textContent = "休憩中";
        guideCountdown.textContent = `${remaining}秒`;
        speechCaption.textContent = `（楽な呼吸でお休みください… 残り${remaining}秒）`;
      } else if (secName.includes("サイクル") || activeItem.duration <= 8) {
        guideCircle.className = "guide-circle hold";
        guideActionText.textContent = "キープ";
        guideCountdown.textContent = `${remaining}秒`;
      } else {
        guideCircle.className = "guide-circle";
        guideActionText.textContent = "ゆっくり";
        guideCountdown.textContent = `${remaining}`;
      }
    }
  }
});

// 曲終了時のキュー進行処理
audio.addEventListener("ended", () => {
  if (currentQueueIndex + 1 < currentQueue.length) {
    // 次のトラックへ
    speechCaption.textContent = "次のメニューへ進みます...";
    guideActionText.textContent = "次へ";
    guideCountdown.textContent = "▶";
    guideCircle.className = "guide-circle rest";
    
    // モバイルの自動再生ポリシーを維持し、途切れることなく次のトラックへ移行
    setTimeout(() => {
      loadQueueItem(currentQueueIndex + 1, true);
    }, 600);
  } else {
    // 全て完了
    releaseWakeLock();
    statusBadge.textContent = "リハビリ完了！";
    statusBadge.className = "status-badge active";
    guideCircle.className = "guide-circle rest";
    guideActionText.textContent = "完了";
    guideCountdown.textContent = "💮";
    speechCaption.textContent = "「お疲れさまでした！本日のメニューは終了です。ゆっくりお休みください。」";
    updatePlayButton(false);
  }
});

// プログレスバークリック
progressBarContainer.addEventListener("click", (e) => {
  if (!audio.duration) return;
  const rect = progressBarContainer.getBoundingClientRect();
  const clickX = e.clientX - rect.left;
  const pct = Math.max(0, Math.min(1, clickX / rect.width));
  audio.currentTime = pct * audio.duration;
});

// ボタン操作
btnPlayPause.addEventListener("click", togglePlayPause);

btnRestart.addEventListener("click", () => {
  audio.currentTime = 0;
  playAudio();
});

btnNext.addEventListener("click", () => {
  if (currentQueueIndex + 1 < currentQueue.length) {
    loadQueueItem(currentQueueIndex + 1, true);
  } else {
    // キューの最初に戻る
    loadQueueItem(0, !audio.paused);
  }
});

// Service Worker登録 (PWA)
function registerServiceWorker() {
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('./sw.js').catch(err => {
        console.log('SW registration failed:', err);
      });
    });
  }
}

// 起動
document.addEventListener("DOMContentLoaded", loadConfig);
