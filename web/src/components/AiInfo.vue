<script setup>
// Meta AI 的結果：標題、圖說草稿（可複製）、精選與動作類型；editor 模式再顯示球員與需確認的原因
import { computed } from "vue";
import { copyText, showToast } from "../lib/share.js";
import { t } from "../lib/i18n.js";

const props = defineProps({ photo: Object, editor: Boolean });
const ai = computed(() => props.photo?.ai || null);
const show = computed(() => props.photo && (props.photo.caption || props.photo.headline || ai.value));
const players = computed(() => (ai.value?.players || []).filter((p) => p.jersey != null || p.name));

async function copy() {
  const text = [props.photo.headline, props.photo.caption].filter(Boolean).join("\n");
  try {
    await copyText(text);
    showToast(t("captionCopied"));
  } catch {
    window.prompt(t("copyCaption"), text);
  }
}
</script>

<template>
  <section v-if="show" class="ai-info" :class="{ review: editor && ai?.needs_review }">
    <p class="ai-badges">
      <span v-if="ai?.pick" class="badge pick">◆ {{ t("aiPick") }}<template v-if="ai.rank"> #{{ ai.rank }}</template></span>
      <span v-if="ai?.moment_label && ai.moment !== 'other'" class="badge">{{ ai.moment_label }}</span>
      <span v-if="editor && ai?.burst?.n > 1" class="badge muted">{{ t("burstFrame", { i: ai.burst.index + 1, n: ai.burst.n }) }}</span>
      <span v-if="editor && ai?.score != null" class="badge muted">{{ t("score", { s: ai.score.toFixed(1) }) }}</span>
      <span v-if="editor && ai?.needs_review" class="badge warn">⚠ {{ t("needsReview") }}</span>
    </p>
    <p v-if="editor && ai?.ai_failed" class="bad small">{{ t("aiFailed") }}</p>
    <h2 v-if="photo.headline" class="ai-headline">{{ photo.headline }}</h2>
    <p v-if="photo.caption" class="ai-caption">{{ photo.caption }}</p>
    <p v-if="editor && players.length" class="ai-players">
      <span v-for="(p, i) in players" :key="i" class="player" :class="{ unverified: !p.verified }">
        #{{ p.jersey ?? "?" }} {{ p.name || "" }}
        <i>{{ Math.round((p.confidence || 0) * 100) }}%<template v-if="!p.verified"> · {{ t("unverified") }}</template></i>
      </span>
    </p>
    <ul v-if="editor && ai?.review_reasons?.length" class="ai-reasons">
      <li v-for="(r, i) in ai.review_reasons" :key="i">{{ r }}</li>
    </ul>
    <button v-if="photo.caption" class="btn small" @click="copy">{{ t("copyCaption") }}</button>
  </section>
</template>
