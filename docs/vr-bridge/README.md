# VR 跟练：网页 / 小程序出码，头显输入

## 使用流程

1. 网页 `/vr` 或小程序「今日训练」底部进入 VR 跟练，确认当前用户。
   无需事先填写训练档案或生成计划；本地开发登录会自动初始化必要的用户记录。
2. 可选附带今日计划，点击「生成连接短码」。六位数字保留前导零，有效期 5 分钟。
3. 头显首页进入「网页连接跟练」，用数字键盘输入短码，点击「匹配并开始」。
4. 后端原子兑换短码，头显保存设备凭据，显示用户身份及默认课表，倒计时 3 秒开始。
5. 可取消倒计时后自选动作或手动开始；失焦、系统暂停和返回首页均取消自动开始。
6. 训练在本地执行。结束后保存、单次上传；失败进入本地队列，准备/报告阶段重试。
7. 网页和小程序手动刷新查看关联或实际训练记录；不轮询、不远程控制、不显示虚构在线状态。

已关联用户再次进入头显需明确确认，不会自动开练。离线可明确沿用缓存身份。
今日计划只是参考，不直接安装成 VR 处方，不改变动作参数，也不推进网页周期计划。
默认课表资产或引擎不可用时阻止自动开始，不静默替换。

## 网页 / 小程序接口

均使用当前用户 Bearer token，不接受请求体中的任意 user_id：

- `POST /vr/pairings`，JSON `{"include_today_plan":false}`：返回 `id`、`code`、`expires_at`（Unix 秒）、`reference`。
- `DELETE /vr/pairings`：取消当前用户尚未兑换的短码；已成功匹配的设备需解除关联。
- `GET /vr/overview`：本人 `connection`、可选 `pairing` 元数据、`today_reference`、最近 20 场 `results`。不返回明文短码或设备凭据。
- `PUT /vr/connection/reference`，JSON `{"enabled":true}`：更新下次准备时可读的参考快照；false 移除。
- `DELETE /vr/connection`：解除本人设备关联、撤销凭据，保留历史结果。

每位用户仅有一个待配对码和一个活动设备。重新生成使之前的码失效；已有活动关联时先解除再申请。
浏览器只在生成响应中取得明文短码，刷新/换端后可重新生成，不从数据库恢复明文码。
状态刷新通过配对 ID 比较，避免显示其他页面已替换的旧短码。

## 头显接口

`POST /vr/device/pairings/redeem`，JSON 字段：

- `code`：六位数字字符串。
- `device_name`：设备名称。
- `device_secret`：头显用安全随机源生成的 32 字节密钥，Base64URL 无填充（43 字符）。只在设备和后端间传递。

成功返回 `state=connected`、`device_token`、`user_id`、可空 `today_reference`、
`advisory_only=true`、`vr_schedule_authoritative=true`、`training_channel=none`。
仅在安全保存凭据并检查本地课表后启动倒计时。设备不再申请或显示短码。
相同短码、相同设备密钥在有效期内重试可恢复同一凭据；不同设备不能重复兑换。
过期/无效/已使用返回 400，状态冲突 409，撤销 410，限流 429；不自动循环重试。

`GET /vr/device/context` 使用设备 Bearer token，供已关联用户下次手动确认读取身份与参考。
撤销返回 410；无效凭据返回 401。活动训练期间禁止桥接请求和同步重试。

`POST /vr/device/results` 使用设备 Bearer token，JSON 保持既有格式：
`client_session_id`、`context_user_id`、带时区的 `started_at`/`ended_at`、
`outcome`（completed/stopped）、`actions`。
每条动作包含 `action_id`、`action_name`，以及可空的 `completed_sets`、`completed_reps`、
`duration_seconds`、`quality_score_01`、`tracking_good_ratio_01`。
只聚合本场正式 capture；不把热身或其他版本历史当作结果。缺少评分时使用 null。
同一用户、场次编号和内容重试不重复记账；编号内容冲突或用户不匹配返回 409。

## 存储、兼容与部署

新表 `vr_pairings` 存放用户、短码哈希、参考快照和兑换状态；现有 `vr_connections`、`vr_results`
继续使用。启动时随现有 metadata.create_all 创建新表，不清空旧关联或历史，不需要改原计划表。
已有活动设备凭据仍可读取 context 和上传 results。
旧方向 `POST /vr/device/pairings` 和 `POST /vr/connection` 明确返回 410，提醒更新三端。

三端访问同一个后端与数据库。Unity 设置 `Resources/ConnectedVR/Settings.serverBaseUrl`，
手机真机修改小程序 API_BASE，不能使用设备自身的 127.0.0.1。保持现有 HTTPS 安全要求。
编辑器结果默认不上传，只有隔离测试用户验收时显式启用 allowEditorResultUploads。

当前账号系统含开发登录，只适用于可信本地/实验室原型；公开部署前替换开发登录并配置服务端密钥。
短码和设备凭据仅存哈希；凭据仅在头显私有加密存储，不写普通偏好或日志。兑换按来源限流，
出码按用户限流；当前限流为单进程实现。

## 代码与验证

- 网页：`frontend/features/vr/`；小程序：`miniprogram/src/features/vr/`。
- Unity 客户端位于独立的 DGTCoach 工程 `Assets/Scripts/ConnectedVR/`，不在本 GitHub 仓库内；接入以本文协议为准。
- 后端：`.venv/Scripts/python.exe -m pytest tests/ -q -o addopts=`。
- 可复现的客户端与浏览器测试：`tests/browser/`，步骤见 [验证及交付说明](validation.md)。
- 各端有独立的响应校验和请求生命周期，取消不会中断原模块请求。相同用户重新显示小程序页面时保留内存中的短码，并通过配对 ID 核实；切换账号会清空。
- 重新申请短码前立即隐藏旧码，避免服务端已换码、响应丢失时仍展示无效旧码。
- 浏览器与编辑器验证使用隔离测试数据，不能代替微信/PICO 真机验收。
