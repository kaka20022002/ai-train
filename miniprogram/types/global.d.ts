/// <reference types="@tarojs/taro" />

declare module "*.png";
declare module "*.jpg";
declare module "*.scss";
declare module "*.css";

declare const defineAppConfig: (config: Record<string, any>) => any;
declare const definePageConfig: (config: Record<string, any>) => any;
