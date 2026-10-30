<script setup>
// 即時監看頁 /live/<即時碼>：給攝影師與編輯，不給客人
//   上半：每台 Pi / 相機的傳輸狀態（連線、待傳、最後一張、速率、電量、FTP 連線數、進行中的上傳）
//   下半：照片依拍攝時間即時流出；分析完顯示星等、AI 精選（◆）與需人工確認（⚠），點開看圖說草稿
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { pageTitle } from "../lib/site.js";
import { fetchLiveFeed, mediaUrl } from "../lib/api.js";
import { errorText, lang, t } from "../lib/i18n.js";
import Lightbox from "./Lightbox.vue";
import BatteryBadge from "./BatteryBadge.vue";

const props = defineProps({ liveKey: { type: String, required: true } });
const scope = { type: "l", key: props.liveKey };

const feed = ref(null);        // 最新一次的裝置 / 統計
const photos = ref(new Map()); // pk → photo，增量合併
const error = ref(null);
const now = ref(Date.now() / 1000);
const serverOffset = ref(0);   // 伺服器時間 − 本機時間
const since = ref(0);
const camera = ref(null);      // 篩選：某台相機 / Pi
const picksOnly = ref(false);  // 篩選：只看 AI 精選（每組連拍選出的 1~3 張）
const lbIndex = ref(-1);
const paused = ref(false);     // 看舊照片時暫停自動捲動到最新（仍會更新資料）
let timer, clock;
const POLL_MS = 3000;

async function refresh() {
  try {
    const d = await fetchLiveFeed(props.liveKey, since.value);
    const first = !feed.value; // 打開頁面時已經在的照片不算「剛到」，不亮框
    if (d.full) photos.value = new Map();
    for (const p of d.photos) photos.value.set(p.pk, { ...p, seen: photos.value.get(p.pk)?.seen ?? (first ? 0 : d.server_time) });
    photos.value = new Map(photos.value); // 觸發更新
    since.value = d.server_time;
    serverOffset.value = d.server_time - Date.now() / 1000;
    feed.value = d;
    document.title = pageTitle(`${d.title} · Live`);
    error.value = null;
  } catch (e) {
    if (!feed.value || e.key === "liveClosed") error.value = e; // 中途被關掉也顯示；開回來會自己恢復
  }
  schedule();
}
const closed = computed(() => error.value?.key === "liveClosed");
function schedule() {
  clearTimeout(timer);
  if (!document.hidden) timer = setTimeout(refresh, POLL_MS);
}
const onVisible = () => !document.hidden && refresh();

onMounted(() => {
  refresh();
  clock = setInterval(() => (now.value = Date.now() / 1000 + serverOffset.value), 1000);
  document.addEventListener("visibilitychange", onVisible);
});
onBeforeUnmount(() => {
  clearTimeout(timer);
  clearInterval(clock);
  document.removeEventListener("visibilitychange", onVisible);
});

// ---- 照片流：最新在前 ----
const sorted = computed(() =>
  [...photos.value.values()].sort((a, b) => (b.taken_at || "").localeCompare(a.taken_at || "") || b.uploaded_at - a.uploaded_at),
);
const visible = computed(() =>
  sorted.value.filter((p) => (!camera.value || camKey(p) === camera.value) && (!picksOnly.value || p.ai?.pick)),
);
const nPicks = computed(() => sorted.value.filter((p) => p.ai?.pick).length);
const isNew = (p) => now.value - p.seen < 12; // 剛到的照片亮一下

// ---- 相機 / Pi ----
// 相機身分以機身序號為準（同型號也分得開）；沒序號就用 Pi 名稱
const camKey = (p) => p.camera || p.device || "?";
const camLabel = (k) => (feed.value?.cameras.find((c) => c.camera === k) ? `…${k.slice(-4)}` : k);
// 每台相機固定一個顏色（序號 hash → 色相）
function camColor(k) {
  let h = 2166136261;
  for (const ch of String(k)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619); // FNV-1a：相鄰名稱也拉得開
  return `hsl(${(h >>> 0) % 360} 70% 60%)`;
}
const cameraChips = computed(() => {
  const m = new Map();
  for (const p of sorted.value) {
    const k = camKey(p);
    m.set(k, (m.get(k) || 0) + 1);
  }
  return [...m].map(([k, n]) => ({ key: k, label: camLabel(k), n, color: camColor(k) }));
});

const ago = (ts) => {
  if (!ts) return t("never");
  const s = Math.max(0, Math.round(now.value - ts));
  return s < 60 ? t("secAgo", { n: s }) : s < 3600 ? t("minAgo", { n: Math.floor(s / 60) }) : t("hourAgo", { n: Math.floor(s / 3600) });
};
const clockText = (iso) => (iso ? iso.slice(11, 19) : "");
const pct = (u) => (u.total ? Math.round((u.received / u.total) * 100) : 0);
const devState = (d) => (!d.online ? "offline" : d.stale ? "stale" : "online");
const devCameras = (d) => (feed.value?.cameras || []).filter((c) => c.device === d.name);
const toggleCam = (k) => (camera.value = camera.value === k ? null : k);
const subtitle = (d) => [d.stats.mode, d.stats.camera_model].filter(Boolean).join(" · ");
// 卡片上的警示：最嚴重的在前；沒有就不顯示這一區
function alerts(d) {
  const a = [];
  if (!d.online) a.push({ tone: "bad", text: t("lastSeen", { t: ago(d.last_seen) }) });
  if (d.online && d.stats.battery != null && d.stats.battery < 10 && !d.stats.charging) a.push({ tone: "bad", text: t("batteryLow") });
  if (d.stats.camera_connected === false) a.push({ tone: "warn", text: t("cameraOff") });
  if (d.stats.failed) a.push({ tone: "bad", text: `${d.stats.failed} ${t("failedUpload")}` });
  if (d.stats.last_error) a.push({ tone: "bad", text: d.stats.last_error });
  if (d.stale) a.push({ tone: "warn", text: t("staleHint") });
  if (d.active_album && d.active_album !== feed.value?.slug) a.push({ tone: "warn", text: t("otherAlbum", { a: d.active_album }) });
  return a;
}
</script>

<template>
  <header class="top live-top">
    <div class="live-head">
      <h1>
        <span class="live-badge" :class="{ off: !feed || closed }"><i></i>LIVE</span>
        <span class="title">{{ error ? errorText(error) : feed?.title || t("loading") }}</span>
      </h1>
      <div v-if="feed && !closed" class="stats">
        <span>{{ feed.shoot_date }}</span>
        <span>{{ t("photos", { n: feed.counts.total || 0 }) }}</span>
        <span v-if="feed.counts.pending" class="warn"><i class="spin"></i>{{ t("nProcessing", { n: feed.counts.pending }) }}</span>
        <span v-if="feed.counts.failed" class="bad">{{ t("nFailed", { n: feed.counts.failed }) }}</span>
        <span v-if="feed.workers.length">{{ t("workers", { n: feed.workers.length }) }}</span>
      </div>
    </div>
    <a v-if="feed" class="btn small" :href="feed.share_url" target="_blank" rel="noopener">★ {{ t("openAlbum") }}</a>
  </header>

  <!-- 相機 / Pi 狀態面板 -->
  <section v-if="feed && !closed" class="devices" :aria-label="t('devices')">
    <p v-if="!feed.devices.length" class="muted">{{ t("noDevices") }}</p>
    <article v-for="d in feed.devices" :key="d.name" class="dev" :class="devState(d)">
      <header class="dev-head">
        <span class="state" :title="d.online ? t('online') : t('offline')"></span>
        <div class="dev-title">
          <strong :title="d.name">{{ d.name }}</strong>
          <span class="dev-sub">{{ subtitle(d) }}</span>
        </div>
        <BatteryBadge
          :level="d.stats.battery" :charging="!!d.stats.charging" :stale="!d.online"
          :stale-text="t('batteryLast', { t: ago(d.last_seen) })"
        />
      </header>

      <div class="metrics">
        <div><b>{{ d.album_count }}</b><span>{{ t("shots") }}</span></div>
        <div :class="{ warn: d.stats.pending > 0 }"><b>{{ d.stats.pending ?? "–" }}</b><span>{{ t("pendingUpload") }}</span></div>
        <div><b>{{ d.per_min || 0 }}</b><span>{{ t("perMin") }}</span></div>
      </div>

      <div v-for="u in d.in_progress" :key="u.filename" class="prog" :title="u.filename">
        <span class="bar"><i :style="{ width: pct(u) + '%' }"></i></span>
        <span class="prog-text"><span class="fname">{{ u.filename }}</span><span>{{ pct(u) }}%</span></span>
      </div>

      <ul v-if="alerts(d).length" class="alerts">
        <li v-for="a in alerts(d)" :key="a.text" :class="a.tone">{{ a.text }}</li>
      </ul>

      <footer class="dev-foot">
        <span>{{ t("lastPhoto") }} {{ ago(d.last_photo_at) }}</span>
        <span v-if="d.stats.mode === 'ftp'" :title="t('ftpClients')">FTP {{ d.stats.ftp_clients ?? 0 }} · {{ d.stats.ftp_received ?? 0 }}</span>
        <span v-if="d.stats.spool_files" :title="t('spoolHint')">spool {{ d.stats.spool_files }} · {{ d.stats.spool_mb }} MB</span>
        <span v-for="c in devCameras(d)" :key="c.camera" class="camtag" :style="{ '--c': camColor(c.camera) }">
          <i class="dot"></i>{{ c.camera.slice(-4) }} <em>{{ c.n }}</em>
        </span>
      </footer>
    </article>
  </section>

  <nav v-if="(cameraChips.length > 1 || nPicks) && !closed" class="filters" :aria-label="t('byCamera')">
    <div class="chips">
      <button v-if="nPicks" class="chip" :aria-pressed="picksOnly" @click="picksOnly = !picksOnly">◆ {{ t("picksOnly") }}<span class="n">{{ nPicks }}</span></button>
      <button class="chip" :aria-pressed="camera === null" @click="camera = null">{{ t("all") }}<span class="n">{{ sorted.length }}</span></button>
      <button
        v-for="c in cameraChips" :key="c.key" class="chip" :aria-pressed="camera === c.key"
        :style="{ '--c': c.color }" @click="toggleCam(c.key)"
      >
        <span class="swatch"></span>{{ c.label }}<span class="n">{{ c.n }}</span>
      </button>
    </div>
  </nav>

  <main class="stream">
    <p v-if="feed && !closed && !visible.length" class="muted center">{{ t("waitingPhotos") }}</p>
    <div v-if="!closed" class="grid">
      <button
        v-for="(p, i) in visible" :key="p.pk" class="cell" :class="[p.status, { fresh: isNew(p), pick: p.ai?.pick }]"
        :style="{ '--c': camColor(camKey(p)) }" :aria-label="p.name" @click="lbIndex = i"
      >
        <img :src="mediaUrl(scope, 's', p.id)" alt="" loading="lazy" decoding="async">
        <span v-if="p.ai?.pick || p.ai?.needs_review || p.raw_name" class="badges">
          <span v-if="p.ai?.pick" class="b-pick" :title="t('aiPick')">◆</span>
          <span v-if="p.ai?.needs_review" class="b-review" :title="t('needsReview')">!</span>
          <span v-if="p.raw_name" class="b-raw">RAW</span>
        </span>
        <span class="meta">
          <i class="dot"></i>
          <span class="cam">{{ camLabel(camKey(p)) }}</span>
          <span class="time">{{ clockText(p.taken_at) }}</span>
          <span v-if="p.status === 'done' && p.stars" class="stars">{{ "★".repeat(p.stars) }}</span>
          <span v-else-if="p.status === 'pending'" class="pend" :title="t('processing')"><i class="spin"></i></span>
          <span v-else-if="p.status === 'failed'" class="fail">{{ t("failed") }}</span>
        </span>
      </button>
    </div>
  </main>

  <Lightbox v-model:index="lbIndex" :photos="visible" :scope="scope" :album-title="feed?.title" editor />
</template>
