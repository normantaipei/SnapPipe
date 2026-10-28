// scope = { type: "a" | "f" | "l", key }：整本相簿（/a/<相簿碼>）、某一個人（/f/<人物碼>）、即時監看（/live/<即時碼>）
// 相簿內的圖片：/media/<相簿碼>/<種類>/<sha>；人物頁：/fm/…；即時頁：/lm/…；單張分享頁：/m/<單張碼>/<種類>
// 種類：s 小縮圖（400）、t 縮圖（800）、p 預覽（2048）、o 原始 JPG、r RAW
// s / t / p 用 photo.id（原始檔 SHA-256，分析後換檔也不變，瀏覽器快取有效）；o / r 用 photo.sha（目前存放的檔）
import { I18nError, t } from "./i18n.js";

const MEDIA_BASE = { a: "media", f: "fm", l: "lm" };
export const mediaUrl = (scope, kind, sha) =>
  `/${MEDIA_BASE[scope.type] || "media"}/${encodeURIComponent(scope.key)}/${kind}/${sha}`;
export const photoMediaUrl = (pk, kind) => `/m/${encodeURIComponent(pk)}/${kind}`;

export const zipUrl = (scope, minStars, fmt = "jpg") => {
  const q = new URLSearchParams();
  if (minStars) q.set("min_stars", minStars);
  if (fmt !== "jpg") q.set("fmt", fmt);
  const base = scope.type === "f" ? "person" : "share";
  return `/api/${base}/${encodeURIComponent(scope.key)}/zip${q.size ? `?${q}` : ""}`;
};

async function getJson(url, notFound, forbidden = "loadFailed") {
  const res = await fetch(url);
  if (!res.ok) throw new I18nError(res.status === 404 ? notFound : res.status === 403 ? forbidden : "loadFailed", { status: res.status });
  return res.json();
}

export const fetchAlbum = (key) => getJson(`/api/share/${encodeURIComponent(key)}`, "albumNotFound");
export const fetchPerson = (key) => getJson(`/api/person/${encodeURIComponent(key)}`, "personNotFound");
export const fetchPhoto = (pk) => getJson(`/api/photo/${encodeURIComponent(pk)}`, "photoNotFound");
export const fetchLiveFeed = (key, since = 0) =>
  getJson(`/api/live/feed/${encodeURIComponent(key)}${since ? `?since=${since}` : ""}`, "albumNotFound", "liveClosed");

export const starText = (n) => (n ? "★".repeat(n) + "☆".repeat(5 - n) : t("unrated"));

export const personName = (p) => p.label || t("personN", { n: p.n });

export const fmtBytes = (b) => (!b ? "" : b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${Math.round(b / 1e6)} MB`);

export const rawExt = (name) => (name ? name.split(".").pop().toUpperCase() : "RAW");
