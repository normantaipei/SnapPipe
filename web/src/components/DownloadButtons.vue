<script setup>
// 單張下載：JPG / RAW 兩顆按鈕＋分享；iPhone / iPad 改成「存到照片」（JPG 與 RAW 各一顆）
import { reactive, watch } from "vue";
import { fmtBytes, rawExt } from "../lib/api.js";
import { sharePhoto, showToast } from "../lib/share.js";
import { canSaveToPhotos, fetchFiles, shareFiles } from "../lib/savePhotos.js";
import { t } from "../lib/i18n.js";

const props = defineProps({ photo: Object, jpgUrl: String, rawUrl: String, shareTitle: String });

const iosJpg = canSaveToPhotos("x.jpg");
const iosRaw = (name) => canSaveToPhotos(name);

// 每種各自的狀態：idle | loading | ready（已下載、等再點一下）
const state = reactive({ jpg: "idle", raw: "idle" });
const cache = { jpg: null, raw: null };

// 換到別張照片就重來
watch(() => props.jpgUrl, () => {
  state.jpg = state.raw = "idle";
  cache.jpg = cache.raw = null;
});

async function save(kind) {
  if (state[kind] === "loading") return;
  try {
    if (!cache[kind]) {
      state[kind] = "loading";
      const item = kind === "jpg"
        ? { url: props.jpgUrl, name: jpgName(props.photo.name) }
        : { url: props.rawUrl, name: props.photo.raw_name };
      cache[kind] = await fetchFiles([item]);
    }
    const r = await shareFiles(cache[kind]);
    state[kind] = r === "needTap" ? "ready" : "idle";
    if (r !== "needTap") cache[kind] = null;
  } catch {
    state[kind] = "idle";
    cache[kind] = null;
    showToast(t("saveFailed"));
  }
}

const jpgName = (n) => (/\.jpe?g$/i.test(n || "") ? n : `${(n || "photo").replace(/\.[^.]+$/, "")}.jpg`);
const label = (kind, text) =>
  state[kind] === "loading" ? t("preparing") : state[kind] === "ready" ? t("tapToSave") : `⬇ ${text}`;
</script>

<template>
  <div class="dl-buttons">
    <button v-if="iosJpg" class="btn small primary" :disabled="state.jpg === 'loading'" @click="save('jpg')">
      {{ label("jpg", t("saveToPhotos")) }}
      <span v-if="state.jpg === 'idle'" class="n">{{ fmtBytes(photo.bytes) }}</span>
    </button>
    <a v-else class="btn small" :href="jpgUrl" download>
      ⬇ JPG <span class="n">{{ fmtBytes(photo.bytes) }}</span>
    </a>
    <template v-if="photo.raw_name">
      <button v-if="iosRaw(photo.raw_name)" class="btn small" :disabled="state.raw === 'loading'" @click="save('raw')">
        {{ label("raw", t("saveRawToPhotos", { ext: rawExt(photo.raw_name) })) }}
        <span v-if="state.raw === 'idle'" class="n">{{ fmtBytes(photo.raw_bytes) }}</span>
      </button>
      <a v-else class="btn small" :href="rawUrl" download>
        ⬇ {{ rawExt(photo.raw_name) }} <span class="n">{{ fmtBytes(photo.raw_bytes) }}</span>
      </a>
    </template>
    <button class="btn small" @click="sharePhoto(photo.pk, shareTitle)">↗ {{ t("share") }}</button>
  </div>
</template>
