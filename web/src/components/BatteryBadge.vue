<script setup>
// Pi 的電量：電池圖示（填色 = 剩餘量）+ 百分比
//   < 20% 橘、< 10% 紅並閃爍；充電中綠色加閃電；裝置離線時灰掉，滑過顯示「最後回報 …」
import { computed } from "vue";
import { t } from "../lib/i18n.js";

const props = defineProps({
  level: { type: Number, default: null },
  charging: { type: Boolean, default: false },
  stale: { type: Boolean, default: false },   // 裝置離線：顯示的是最後一次回報的值
  staleText: { type: String, default: "" },
});

const pct = computed(() => Math.max(0, Math.min(100, Math.round(props.level ?? 0))));
const tone = computed(() =>
  props.stale ? "stale" : props.charging ? "charging" : pct.value < 10 ? "critical" : pct.value < 20 ? "low" : "ok",
);
const title = computed(() =>
  [
    `${t("battery")} ${pct.value}%`,
    props.charging ? t("charging") : tone.value === "critical" || tone.value === "low" ? t("batteryLow") : "",
    props.stale ? props.staleText : "",
  ].filter(Boolean).join(" · "),
);
</script>

<template>
  <span v-if="level != null" class="battery" :class="tone" :title="title" :aria-label="title">
    <svg viewBox="0 0 26 14" width="24" height="13" aria-hidden="true">
      <rect x="0.75" y="0.75" width="21.5" height="12.5" rx="3" fill="none" stroke="currentColor" stroke-width="1.5" />
      <rect x="23.4" y="4.5" width="2" height="5" rx="1" fill="currentColor" />
      <rect x="2.75" y="2.75" :width="Math.max(1.5, 17.5 * pct / 100)" height="8.5" rx="1.5" fill="currentColor" />
      <path v-if="charging" d="M12.8 1.6 8.2 7.6h3.2l-1.4 4.8 4.8-6.2h-3.3z" fill="var(--surface)" stroke="var(--surface)"
            stroke-width="0.6" stroke-linejoin="round" />
    </svg>
    <span class="pct">{{ pct }}%</span>
  </span>
</template>
