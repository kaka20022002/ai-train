import { API_BASE } from "./config";
import Taro from "@tarojs/taro";

/**
 * 将教程媒体路径转为小程序可请求的绝对地址。
 * - 相对路径：拼 API_BASE
 * - 已是绝对地址：强制改写到 API_BASE（避免 127.0.0.1 / localhost 不一致）
 */
export function mediaUrl(url?: string | null): string {
  if (!url) return "";
  const base = API_BASE.replace(/\/$/, "");

  if (url.startsWith("http://") || url.startsWith("https://")) {
    const pathStart = url.indexOf("/", url.indexOf("//") + 2);
    const path = pathStart >= 0 ? url.slice(pathStart) : "/";
    return `${base}${path}`;
  }

  return `${base}${url.startsWith("/") ? "" : "/"}${url}`;
}

/** 不依赖 guide-meta 返回的 host，直接按动作名拼媒体地址 */
export function exerciseMediaUrl(name: string, frame: number): string {
  const base = API_BASE.replace(/\/$/, "");
  return `${base}/exercises/media/${encodeURIComponent(name)}/${frame}`;
}

/**
 * 真机上 Image 直链局域网 HTTP 常失败；先 downloadFile 到本地临时路径再展示。
 */
export async function downloadMediaLocal(remoteUrl: string): Promise<string> {
  if (!remoteUrl) throw new Error("empty url");
  // 已是本地临时文件
  if (
    remoteUrl.startsWith("wxfile://") ||
    remoteUrl.startsWith("http://tmp") ||
    remoteUrl.startsWith("https://tmp") ||
    remoteUrl.includes("://tmp/")
  ) {
    return remoteUrl;
  }

  const res = await Taro.downloadFile({ url: remoteUrl });
  if (res.statusCode >= 200 && res.statusCode < 300 && res.tempFilePath) {
    return res.tempFilePath;
  }
  throw new Error(`download ${res.statusCode || "fail"}`);
}

export async function downloadMediaFrames(
  remoteUrls: string[]
): Promise<string[]> {
  const out: string[] = [];
  for (const url of remoteUrls) {
    out.push(await downloadMediaLocal(url));
  }
  return out;
}
