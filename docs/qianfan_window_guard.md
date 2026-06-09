# 千帆窗口守卫

## 目标

这套小工具只解决一个问题：

- 任务自己打开的 Chrome 窗口，任务结束后自己关闭
- 用户原来已经打开的店铺后台窗口，不碰

它不是取数工具，也不是页面交互工具；它只是千帆相关自动任务的“窗口所有权守卫”。

## 正式目录

- 扩展目录：`chrome_extensions/qianfan_window_guard`
- 检查脚本：`scripts/check_qianfan_window_guard.py`
- Chrome 残留清理脚本：`scripts/cleanup_chrome_automation_residue.sh`

## 正式口径

1. 后续千帆相关任务，默认优先检查当前 profile 有没有装这个扩展。
2. 已安装且启用时，正式开页口径固定走“插件桥接页 -> 任务页 -> 按 `task_id` 回收本轮窗口”。
3. 插件桥接页只负责发起打开/关闭指令，发完就立即自关；正常情况下你几乎看不到它停留。
4. 没装时，不把业务任务直接判失败；允许降级到现有窗口策略，但要明确记录这是降级执行，并提醒“这个店铺 profile 先装插件”。
5. 如果是首次接入的新店铺 profile，应先在该 profile 里加载一次本地 unpacked 扩展。
6. 后续不再允许用 macOS 菜单悬停方式探查 Chrome 设置；需要确认 `允许 Apple 事件中的 JavaScript` 时，优先读 profile `Preferences` 里的 `browser.allow_javascript_apple_events`。
7. 任何一步如果打开了系统菜单、右键菜单或文件选择器，必须在同一步完成关闭；如果没关掉，先做收尾，不继续测。
8. 如果为了排障强退过 Chrome，恢复前必须先清理自动化测试残留，再决定是否清理 `Singleton*` 锁文件。
9. 现有千帆任务、后续新增千帆任务、以及后续新接入的店铺 profile，默认都要复用这套窗口守卫；只允许继续补接入，不允许再各自维护一套新关页方案。

## 安装方式

当前正式口径固定是本地 unpacked 扩展：

1. 用目标店铺 profile 打开 `chrome://extensions/`
2. 打开“开发者模式”
3. 选择“加载已解压的扩展程序”
4. 选择目录 `chrome_extensions/qianfan_window_guard`

说明：

- 这是本地小工具，不依赖 Chrome 应用商店
- 以后如果店铺 profile 增加，只需要按同一方式补一次
- 如果已经加载过桌面里的真实扩展目录，后续更新时只需要在对应 profile 的扩展页点一次“重新加载”，不需要重装

## 检查方式

检查所有 profile：

```bash
python3 scripts/check_qianfan_window_guard.py --json
```

只检查单个 profile：

```bash
python3 scripts/check_qianfan_window_guard.py --profile-directory "Default" --json
```

为已配置的千帆店铺统一打开插件详情页：

```bash
python3 scripts/open_qianfan_window_guard_pages.py
```

补充：

- 这个检查脚本现在会一起输出 `browser_js_allowed`，用于确认当前 profile 是否开启了 Apple 事件里的页内 JavaScript。
- 判断这个开关时，后续固定看脚本输出，不再用菜单探查。
- 检查时不再强依赖“扩展必须装在仓库目录”；只要目标 profile 里加载的是同一份 `Qianfan Window Guard` unpacked 扩展，即使实际目录放在桌面或别的绝对路径，也会识别成已安装。
- `scripts/open_qianfan_window_guard_pages.py` 会优先给已启用这套扩展的 profile 打开对应详情页；如果某个新店铺 profile 还没装，会退回打开 `chrome://extensions/`，提醒先安装。

检查 Chrome 自动化残留：

```bash
bash scripts/cleanup_chrome_automation_residue.sh status
```

## 自测方式

1. 在目标 profile 里打开扩展的设置页
2. 点“打开并自动关闭”
3. 肉眼确认：
   - 新开了一个独立窗口
   - 这个独立窗口会自己关闭
   - 原来业务窗口没有被关掉

补充：

- 当前默认自动关闭延迟是 `60` 秒，不再用之前的 `8` 秒默认值
- 扩展页现在内置两档快捷时长：`短任务 60 秒`、`长任务 10 分钟`
- 后续真正跑店铺后台时，这里的目标地址会换成任务自己的店铺页面；`60` 秒只是默认收尾时间，不是固定死值
- 长任务不需要以后再单独开发另一套扩展；正式口径就是继续复用这一套，只在任务启动时切到 `10` 分钟或由脚本直接传更长时长
- 当前正式已验证：好评已上评同步链路会通过这套桥接方案自己打开评价页，并在任务完成后自己关闭任务页；状态文件里的 `cleanup_status` 也会单独记录成 `closed` / `warning`

## 异常恢复

如果出现“强退后点 Chrome 没反应 / 资料窗口不出来 / 右键菜单卡住”：

1. 先停止当前测试，不继续点菜单、不继续开新窗口。
2. 跑 `bash scripts/cleanup_chrome_automation_residue.sh cleanup`，先清掉自动化测试残留。
3. 只有在当前没有真实 Chrome 主进程时，才允许清理 `SingletonLock / SingletonCookie / SingletonSocket`。
4. 重新拉起 Chrome 后，优先用 Chrome 自带会话恢复找回用户原窗口。
5. 收尾时只关闭本轮自建的空白页、扩展页、测试页，不碰用户原来的业务页。

这次事故的正式结论：

- Playwright 临时 Chrome 进程残留，会干扰用户正常 Chrome 启动。
- 强退后的陈旧 `Singleton*` 锁，会让“点图标没反应”持续存在。
- 菜单探查如果没有即时收掉，会直接把用户桌面卡死。

## 维护边界

- 这套扩展只维护“窗口所有权”
- 不负责页面找控件
- 不负责导出、搜索、读取业务数据
- 不负责绕过登录、验证码或风控
