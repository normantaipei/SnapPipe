<script setup>
// 整本下載：JPG / RAW / JPG+RAW，依目前的星等篩選
// iPhone / iPad 多「存到照片（JPG）」：ZIP 只會進「檔案」App，要進相簿得分批交給系統分享選單
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { fmtBytes, mediaUrl, zipUrl } from "../lib/api.js";
import { showToast } from "../lib/share.js";
import { canSaveToPhotos, chunkUnits, fetchFiles, shareFiles } from "../lib/savePhotos.js";
import { t } from "../lib/i18n.js";

const props = defineProps({ scope: Object, photos: Array, minStars: Number });
const open = ref(false);
const root = ref(null);
const ios = canSaveToPhotos("x.jpg");

const sum = (f) => props.photos.reduce((a, p) => a + (f(p) || 0), 0);
const rawCount = computed(() => props.photos.filter((p) => p.raw_name).length);
const options = computed(() => {
  const opts = [{ fmt: "jpg", label: "JPG", count: props.photos.length, bytes: sum((p) => p.bytes) }];
  if (rawCount.value) {
    opts.push({ fmt: "raw", label: "RAW", count: rawCount.value, bytes: sum((p) => p.raw_bytes) });
    opts.push({ fmt: "all", label: "JPG + RAW", count: props.photos.length + rawCount.value,
                bytes: sum((p) => p.bytes) + sum((p) => p.raw_bytes) });
  }
  return opts;
});
// 存到照片只做 JPG；RAW 在 iOS 照片 App 不一定收得進去，照舊下載 ZIP 到「檔案」
const saveOptions = computed(() => (ios ? options.value.filter((o) => o.fmt === "jpg") : []));

// ── 存到照片（分批）──
// job = { batches, i, done, files, progress }；files 有值 = 這批已下載好、等使用者點一下
const job = ref(null);
let cancelled = false;

const jpgName = (n) => (/\.jpe?g$/i.test(n || "") ? n : `${(n || "photo").replace(/\.[^.]+$/, "")}.jpg`);
function unitsFor(fmt) {
  const units = [];
  for (const p of props.photos) {
    const u = [];
    if (fmt !== "raw") u.push({ url: mediaUrl(props.scope, "o", p.sha), name: jpgName(p.name), bytes: p.bytes });
    if (fmt !== "jpg" && p.raw_name) u.push({ url: mediaUrl(props.scope, "r", p.sha), name: p.raw_name, bytes: p.raw_bytes });
    if (u.length) units.push(u);
  }
  return units;
}

async function startSave(fmt) {
  open.value = false;
  cancelled = false;
  job.value = { batches: chunkUnits(unitsFor(fmt)), i: 0, done: 0, files: null, progress: 0 };
  await nextBatch();
}

async function nextBatch() {
  const j = job.value;
  if (!j || cancelled) return;
  if (j.i >= j.batches.length) {
    showToast(t("savedN", { n: j.done }));
    job.value = null;
    return;
  }
  try {
    j.files = null;
    j.progress = 0;
    const files = await fetchFiles(j.batches[j.i], (n) => { if (job.value) job.value.progress = n; });
    if (cancelled) return;
    j.files = files;
    // 第一批通常還在點擊的時效內，直接開分享選單；不行就等使用者點按鈕
    if (j.i === 0) await shareBatch();
  } catch {
    showToast(t("saveFailed"));
    job.value = null;
  }
}

async function shareBatch() {
  const j = job.value;
  if (!j?.files) return;
  try {
    const r = await shareFiles(j.files);
    if (r === "needTap") return;        // 按鈕顯示「存第 i/n 批」，等使用者點
    if (r === "cancel") { job.value = null; return; }
    j.done += j.files.length;
    j.i += 1;
    await nextBatch();
  } catch {
    showToast(t("saveFailed"));
    job.value = null;
  }
}

function cancelSave() {
  cancelled = true;
  job.value = null;
}

const onDoc = (e) => { if (!root.value?.contains(e.target)) open.value = false; };
const onKey = (e) => { if (e.key === "Escape") open.value = false; };
onMounted(() => { document.addEventListener("click", onDoc); addEventListener("keydown", onKey); });
onBeforeUnmount(() => { cancelled = true; document.removeEventListener("click", onDoc); removeEventListener("keydown", onKey); });
</script>

<template>
  <div ref="root" class="dl-menu">
    <div v-if="job" class="save-job">
      <button v-if="job.files" class="btn primary" @click="shareBatch">
        ⬇ {{ t("saveBatch", { i: job.i + 1, n: job.batches.length, k: job.files.length }) }}
      </button>
      <span v-else class="btn" aria-live="polite">
        {{ t("preparingBatch", { i: job.i + 1, n: job.batches.length, k: job.progress, m: job.batches[job.i].length }) }}
      </span>
      <button class="btn small" @click="cancelSave">{{ t("cancel") }}</button>
    </div>
    <button v-else class="btn" :aria-expanded="open" @click="open = !open">
      ⬇ {{ minStars ? t("downloadStars", { n: minStars }) : t("downloadAll") }} ({{ photos.length }})<span class="caret">▾</span>
    </button>
    <div v-if="open" class="dl-pop" role="menu">
      <a v-for="o in saveOptions" :key="'save-' + o.fmt" role="menuitem" href="#" @click.prevent="startSave(o.fmt)">
        <strong>{{ t("saveToPhotosFmt", { fmt: o.label }) }}</strong>
        <span class="muted">{{ t("files", { n: o.count }) }} · {{ fmtBytes(o.bytes) }}</span>
      </a>
      <a
        v-for="o in options" :key="o.fmt" role="menuitem" :href="zipUrl(scope, minStars, o.fmt)"
        download @click="open = false"
      >
        <strong>{{ o.label }}{{ ios ? " ZIP" : "" }}</strong>
        <span class="muted">{{ t("files", { n: o.count }) }} · {{ fmtBytes(o.bytes) }}</span>
      </a>
      <p v-if="ios" class="muted note">{{ t("zipToFiles") }}</p>
      <p v-if="!rawCount" class="muted note">{{ t("noRaw") }}</p>
    </div>
  </div>
</template>
