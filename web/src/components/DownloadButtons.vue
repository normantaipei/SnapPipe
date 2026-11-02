<script setup>
// 單張下載：JPG / RAW 兩顆按鈕＋分享；iPhone / iPad 多一顆「存到照片」
import { ref, watch } from "vue";
import { fmtBytes, rawExt } from "../lib/api.js";
import { sharePhoto, showToast } from "../lib/share.js";
import { canSaveToPhotos, fetchFiles, shareFiles } from "../lib/savePhotos.js";
import { t } from "../lib/i18n.js";

const props = defineProps({ photo: Object, jpgUrl: String, rawUrl: String, shareTitle: String });

const ios = canSaveToPhotos();
const state = ref("idle"); // idle | loading | ready
let files = null;

// 換到別張照片就重來
watch(() => props.jpgUrl, () => { state.value = "idle"; files = null; });

async function saveToPhotos() {
  if (state.value === "loading") return;
  try {
    if (!files) {
      state.value = "loading";
      files = await fetchFiles([{ url: props.jpgUrl, name: props.photo.name }]);
    }
    const r = await shareFiles(files);
    state.value = r === "needTap" ? "ready" : "idle";
    if (r !== "needTap") files = null;
  } catch {
    state.value = "idle";
    files = null;
    showToast(t("saveFailed"));
  }
}
</script>

<template>
  <div class="dl-buttons">
    <button v-if="ios" class="btn small primary" :disabled="state === 'loading'" @click="saveToPhotos">
      {{ state === "loading" ? t("preparing") : state === "ready" ? t("tapToSave") : `⬇ ${t("saveToPhotos")}` }}
      <span v-if="state === 'idle'" class="n">{{ fmtBytes(photo.bytes) }}</span>
    </button>
    <a v-else class="btn small" :href="jpgUrl" download>
      ⬇ JPG <span class="n">{{ fmtBytes(photo.bytes) }}</span>
    </a>
    <a v-if="photo.raw_name" class="btn small" :href="rawUrl" download>
      ⬇ {{ rawExt(photo.raw_name) }} <span class="n">{{ fmtBytes(photo.raw_bytes) }}</span>
    </a>
    <button class="btn small" @click="sharePhoto(photo.pk, shareTitle)">↗ {{ t("share") }}</button>
  </div>
</template>
