import type { Metadata } from "next";
import { VrFollowPage } from "@/features/vr/VrFollowPage";

export const metadata: Metadata = { title: "VR 跟练 · AI 健身教练" };

export default function Page() {
  return <VrFollowPage />;
}
