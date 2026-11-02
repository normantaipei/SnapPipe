// iPhone / iPad 存到「照片」App
//
// iOS Safari 的 <a download> 一律存進「檔案」App 的「下載項目」，不會進相簿；
// 網頁唯一能把照片放進相簿的方式，是把檔案交給系統分享選單（navigator.share），
// 使用者再點「儲存影像」/「儲存 N 張影像」。RAW（ARW、CR3、NEF、DNG…）也一樣：
// 檔案帶上正確的 MIME，iOS 才認得是影像、分享選單才會出現「儲存影像」。
//
// 限制：
// - 只有 https 才有 navigator.share（區網的 http://<IP>:8080 沒有，會退回一般下載）
// - share() 必須在點擊後很快呼叫；先下載原圖再分享時，iOS 可能判定「不是使用者動作」
//   丟 NotAllowedError。這時回傳 "needTap"，介面改成「再點一下儲存」，用第二次點擊分享。

const MIME = {
  jpg: "image/jpeg", jpeg: "image/jpeg",
  arw: "image/x-sony-arw", srf: "image/x-sony-srf", sr2: "image/x-sony-sr2",
  cr2: "image/x-canon-cr2", cr3: "image/x-canon-cr3", crw: "image/x-canon-crw",
  nef: "image/x-nikon-nef", nrw: "image/x-nikon-nrw",
  raf: "image/x-fuji-raf", orf: "image/x-olympus-orf", rw2: "image/x-panasonic-rw2",
  dng: "image/x-adobe-dng", pef: "image/x-pentax-pef", srw: "image/x-samsung-srw",
};
export const mimeOf = (name) => MIME[(name || "").split(".").pop().toLowerCase()] || "application/octet-stream";

const isIOS = () => typeof navigator !== "undefined" && (
  /iPhone|iPad|iPod/.test(navigator.userAgent)
  || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)); // iPadOS 會自稱 Mac

// 這種檔案能不能經分享選單存到照片（name 例：x.jpg、DSC01234.ARW）
export function canSaveToPhotos(name = "x.jpg") {
  if (typeof navigator === "undefined" || !navigator.share || !navigator.canShare || !isIOS()) return false;
  try {
    return navigator.canShare({ files: [new File([new Uint8Array(1)], name, { type: mimeOf(name) })] });
  } catch {
    return false;
  }
}

// items: [{ url, name }]；onProgress(已完成個數)
export async function fetchFiles(items, onProgress) {
  const files = [];
  for (const it of items) {
    const res = await fetch(it.url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    files.push(new File([blob], it.name, { type: mimeOf(it.name), lastModified: Date.now() }));
    onProgress?.(files.length);
  }
  return files;
}

// 回傳 "ok"（已交給分享選單）、"cancel"（使用者關掉選單）、"needTap"（要再點一次）
export async function shareFiles(files) {
  try {
    await navigator.share({ files });
    return "ok";
  } catch (e) {
    if (e.name === "AbortError") return "cancel";
    if (e.name === "NotAllowedError") return "needTap";
    throw e;
  }
}

// 分批：分享選單一次塞太多原圖，iPhone 記憶體會不夠。
// units 是 [[item, …], …]，同一張的 JPG + RAW 是一個 unit，不會被拆到兩批
export function chunkUnits(units, maxFiles = 20, maxBytes = 200e6) {
  const out = [];
  let cur = [], bytes = 0;
  for (const u of units) {
    const b = u.reduce((a, it) => a + (it.bytes || 0), 0);
    if (cur.length && (cur.length + u.length > maxFiles || bytes + b > maxBytes)) {
      out.push(cur);
      cur = [];
      bytes = 0;
    }
    cur.push(...u);
    bytes += b;
  }
  if (cur.length) out.push(cur);
  return out;
}
