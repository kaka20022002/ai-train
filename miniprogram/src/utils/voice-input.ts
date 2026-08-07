import Taro from "@tarojs/taro";
import { API_BASE, STORAGE_KEYS } from "./config";

export type VoiceStatus = "idle" | "recording" | "recognizing" | "error";

type RecognizeCallbacks = {
  onStart?: () => void;
  onResult: (text: string) => void;
  onError: (message: string) => void;
  onStop?: () => void;
};

/**
 * 语音输入：RecorderManager 录音 → 上传后端 /stt。
 *
 * 说明：微信「同声传译」插件在测试号下会报「插件未授权」并阻断启动，
 * 因此当前默认不走插件。正式 AppID 开通插件后，可再在 app.config 声明并扩展此处。
 */
export function createVoiceInput() {
  let mode: "recorder" | null = null;
  let recorder: Taro.RecorderManager | null = null;
  let activeCb: RecognizeCallbacks | null = null;

  const ensureMicPermission = async () => {
    try {
      const setting = await Taro.getSetting();
      if (setting.authSetting["scope.record"] === false) {
        await Taro.showModal({
          title: "需要麦克风权限",
          content: "请在设置中开启麦克风，以便语音向教练提问。",
          confirmText: "去设置",
          success: (res) => {
            if (res.confirm) Taro.openSetting({});
          },
        });
        return false;
      }
      if (setting.authSetting["scope.record"] !== true) {
        await Taro.authorize({ scope: "scope.record" });
      }
      return true;
    } catch {
      Taro.showToast({ title: "未获得麦克风权限", icon: "none" });
      return false;
    }
  };

  const uploadForStt = async (filePath: string): Promise<string> => {
    const token = Taro.getStorageSync(STORAGE_KEYS.token) || "";
    const header: Record<string, string> = {};
    if (token) header.Authorization = `Bearer ${token}`;

    const upload = await Taro.uploadFile({
      url: `${API_BASE}/stt`,
      filePath,
      name: "file",
      header,
      formData: {},
    });

    let parsed: { text?: string; detail?: string } = {};
    try {
      parsed =
        typeof upload.data === "string"
          ? JSON.parse(upload.data)
          : (upload.data as { text?: string; detail?: string });
    } catch {
      throw new Error("语音识别返回异常");
    }

    if (upload.statusCode < 200 || upload.statusCode >= 300) {
      const detail =
        typeof parsed.detail === "string"
          ? parsed.detail
          : `识别失败(${upload.statusCode})`;
      throw new Error(detail);
    }

    const text = (parsed.text || "").trim();
    if (!text) throw new Error("没有识别到内容，请再说一次");
    return text;
  };

  const ensureRecorder = () => {
    if (recorder) return recorder;
    recorder = Taro.getRecorderManager();
    recorder.onStart(() => activeCb?.onStart?.());
    recorder.onStop(async (res) => {
      const cb = activeCb;
      activeCb = null;
      mode = null;
      cb?.onStop?.();
      const path = res?.tempFilePath;
      if (!path) {
        cb?.onError("录音失败，未生成文件");
        return;
      }
      try {
        const text = await uploadForStt(path);
        cb?.onResult(text);
      } catch (e: any) {
        const msg = String(e?.message || e || "语音识别失败");
        cb?.onError(msg.length > 80 ? `${msg.slice(0, 80)}…` : msg);
      }
    });
    recorder.onError((err) => {
      const cb = activeCb;
      activeCb = null;
      mode = null;
      cb?.onStop?.();
      cb?.onError(err?.errMsg || "录音出错");
    });
    return recorder;
  };

  const start = async (cb: RecognizeCallbacks) => {
    const ok = await ensureMicPermission();
    if (!ok) {
      cb.onError("未获得麦克风权限");
      return;
    }

    try {
      mode = "recorder";
      activeCb = cb;
      const mgr = ensureRecorder();
      mgr.start({
        duration: 60000,
        sampleRate: 16000,
        numberOfChannels: 1,
        encodeBitRate: 48000,
        format: "mp3",
      });
    } catch (e: any) {
      mode = null;
      activeCb = null;
      cb.onError(
        e?.message ||
          "无法开始录音。请在后端配置 WHISPER_API_KEY 以启用语音识别。"
      );
    }
  };

  const stop = () => {
    try {
      if (mode === "recorder") recorder?.stop?.();
    } catch {
      // ignore
    }
  };

  return {
    usingPlugin: () => false,
    start,
    stop,
  };
}
