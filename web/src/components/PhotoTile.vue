<script setup>
import { ref } from "vue";
import { mediaUrl, starText } from "../lib/api.js";
import { t } from "../lib/i18n.js";

defineProps({ scope: Object, photo: Object, w: Number, h: Number });
defineEmits(["open"]);
const loaded = ref(false);
</script>

<template>
  <button
    class="tile" :style="{ width: `${w}px`, height: `${h}px` }"
    :aria-label="`${photo.name}, ${starText(photo.stars)}`" @click="$emit('open')"
  >
    <img
      :src="mediaUrl(scope, 't', photo.id)" alt="" loading="lazy" decoding="async"
      :class="{ loaded }" @load="loaded = true"
    >
    <span v-if="photo.status === 'pending'" class="pending" :title="t('processing')">…</span>
  </button>
</template>
