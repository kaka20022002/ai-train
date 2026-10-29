import { View, Text } from "@tarojs/components";
import Taro from "@tarojs/taro";
import "./entry.scss";

export default function VrEntry() {
  return (
    <View
      className="vr-entry"
      onClick={() => Taro.navigateTo({ url: "/pages/vr/index" })}
    >
      <View className="vr-entry-icon">
        <View className="vr-entry-lens" />
      </View>
      <View className="vr-entry-copy">
        <Text className="vr-entry-title">VR 跟练</Text>
        <Text className="vr-entry-subtitle">连接头显，跟着数字教练练</Text>
      </View>
      <Text className="vr-entry-arrow">›</Text>
    </View>
  );
}
