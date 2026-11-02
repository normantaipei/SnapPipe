// iPhone / iPad 存到「照片」App
//
// iOS Safari 的 <a download> 一律存進「檔案」App 的「下載項目」，不會進相簿；
// 網頁唯一能把照片放進相簿的方式，是把檔案交給系統分享選單（navigator.share），
// 使用者再點「儲存影像」/「儲存 N 張影像」。
//
// 限制：
// - 只有 https 才有 navigator.share（區網的 http://<IP>:8080 沒有，會退回一般下載）
// - share() 必須在點擊後很快呼叫；先下載原圖再分享時，iOS 可能判定「不是使用者動作」
//   丟 NotAllowedError。這時回傳 "needTap"，介面改成「再點一下儲存」，用第二次點擊分享。

export function canSaveToPhotos() {
  if (typeof navigator === "undefined" || !navigator.share || !navigator.canShare) return false;
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent)
    || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1); // iPadOS 會自稱 Mac
  if (!ios) return false;
  try {
    return navigator.canShare({ files: [new File([new Uint8Array(1)], "x.jpg", { type: "image/jpeg" })] });
  } catch {
    return false;
  }
}

// items: [{ url, name }]；onProgress(已完成張數)
export async function fetchFiles(items, onProgress) {
  const files = [];
  for (const it of items) {
    const res = await fetch(it.url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const name = /\.jpe?g$/i.test(it.name || "") ? it.name : `${(it.name || "photo").replace(/\.[^.]+$/, "")}.jpg`;
    files.push(new File([blob], name, { type: "image/jpeg", lastModified: Date.now() }));
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

// 整本存到照片時一批幾張：分享選單一次塞太多原圖，iPhone 記憶體會不夠
export function chunkPhotos(list, maxFiles = 20, maxBytes = 200e6) {
  const out = [];
  let cur = [], bytes = 0;
  for (const p of list) {
    const b = p.bytes || 0;
    if (cur.length && (cur.length >= maxFiles || bytes + b > maxBytes)) {
      out.push(cur);
      cur = [];
      bytes = 0;
    }
    cur.push(p);
    bytes += b;
  }
  if (cur.length) out.push(cur);
  return out;
}
