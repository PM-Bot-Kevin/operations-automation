# 运营自动化

这个工作区当前已经按“正式可长期维护”的最小标准初始化完成，重点不是业务功能，而是先把版本治理、正式发布、回滚、GitHub 备份、跨工作区协作约束固化到仓库里。

## 当前工作区信息

- 工作区名称：`运营自动化`
- 工作区绝对路径：`/Users/luogic/Code/运营自动化`
- GitHub 仓库 SSH 地址：`git@github.com:PM-Bot-Kevin/operations-automation.git`
- 正式环境类型：`本地正式环境`
- 可能依赖的其他工作区：`无`

## 当前正式运行方式

当前仓库在初始化前是空目录，没有既有正式运行链路。现在起正式口径固定为本地正式环境发布链路：

```text
运营自动化/
  releases/         # 历史正式代码版本，不入 Git
  current -> ...    # 当前正式代码入口，不入 Git
  runtime/          # 正式运行数据 / 日志预留目录，不入 Git
  release-log/      # 发布 / 回滚日志，不入 Git
```

- 正式发布只切代码版本，不覆盖 `runtime/`
- 正式回滚只切 `current`
- GitHub 备份只备份仓库代码，不备份真实运行数据

## 正式发布与回滚

- 发布前固定自动先跑治理校验：`python3 scripts/validate_workspace_governance.py`
- 正式发布命令：

```bash
bash scripts/release_workspace.sh --summary "本次变更说明"
```

- 查看发布 / 回滚记录：

```bash
python3 scripts/show_release_history.py
```

- 回滚到上一版：

```bash
bash scripts/rollback_workspace.sh
```

- 回滚到指定版本：

```bash
bash scripts/rollback_workspace.sh --to <release-id>
```

更多维护步骤见 [HANDOVER.md](/Users/luogic/Code/运营自动化/HANDOVER.md) 和 [docs/release_and_rollback.md](/Users/luogic/Code/运营自动化/docs/release_and_rollback.md)。

## GitHub 备份

- 手动备份：

```bash
bash scripts/github_backup.sh
```

- 自动备份安装：

```bash
bash scripts/install_backup_launchagent.sh
```

- 自动备份固定时间：
  - 每天 `10:00` 运行自动备份
  - 每天 `10:20` 运行自动巡检
  - 成功不通知
  - 失败保留日志并发本机通知

注意：

- GitHub 是代码备份，不是真实业务数据备份
- `runtime/`、`releases/`、`current`、`release-log/`、`.env`、密钥、缓存、日志都不会备份进 GitHub
- 当前 GitHub SSH 远端：

```bash
git@github.com:PM-Bot-Kevin/operations-automation.git
```

详细说明见 [BACKUP.md](/Users/luogic/Code/运营自动化/BACKUP.md)。

## 飞书图片整理

如果你只是想把飞书表里的好评图片直接导出到桌面，用一句自然语言就行：

```bash
python3 scripts/export_feishu_order_images.py "帮我导出今天要上的好评"
```

也支持这些说法：

```bash
python3 scripts/export_feishu_order_images.py "帮我导出明天要上的好评"
python3 scripts/export_feishu_order_images.py "帮我导出近三天要上的好评"
python3 scripts/export_feishu_order_images.py "帮我导出5月29号要上的好评"
python3 scripts/export_feishu_order_images.py "把昨天的好评图片导出来"
python3 scripts/export_feishu_order_images.py "导出最近5天的图片"
```

导出结果会直接放到桌面文件夹里，文件名按订单号命名：

```text
~/Desktop/好评图片_2026-05-29/
  P795164060902509861_1.png
  P795165179384467271_1.jpg
  P795165179384467271_2.png
```

- 同一订单多张图会自动变成 `订单号_1`、`订单号_2`
- 默认只下载 `配图` 字段
- 日期筛选依据固定看 `上评日期`
- 在 Codex 里使用这个工作区时，直接对助手说你的自然语言需求即可，助手应直接代为执行，不需要你自己跑命令

## 千帆后台访问

当前工作区已经支持复用你本机现有的 Chrome 店铺资料，重新打开小红书千帆后台页面，而不是强依赖某个已经打开的标签页。

对应脚本：

```bash
python3 scripts/xhs_qianfan_access.py profiles
python3 scripts/xhs_qianfan_access.py open --store "考拉小姐慢慢来" --page orders
python3 scripts/xhs_qianfan_access.py open --store "考拉小姐慢慢来" --page aftersale
python3 scripts/xhs_qianfan_access.py open --store "考拉小姐慢慢来" --page comments
```

默认规则：

- 优先复用本机现有 Chrome 店铺资料，不重复维护一套新资料
- 重新打开后台页时，不依赖当前已有 tab
- 涉及店铺后台时默认只读；未经用户明确允许，不做修改、删除、发货、备注、上传等写操作
- 涉及店铺后台时按最小操作原则执行，尽量减少刷新、重复点击和无关跳转，优先在已有页面状态上完成读取
- 涉及千帆后台的极度保守执行规则，以 [docs/xhs_qianfan_safety.md](/Users/luogic/Code/运营自动化/docs/xhs_qianfan_safety.md) 和 [config/xhs_qianfan_guardrails.json](/Users/luogic/Code/运营自动化/config/xhs_qianfan_guardrails.json) 为准，后续所有千帆需求默认共用

## 飞书 SKU 补齐

当前工作区已经新增“好评表缺失 SKU 补齐”的正式能力，对应脚本是 `scripts/fill_feishu_order_skus.py`。

这项能力的正式口径固定是三段式：

```text
1. 先从飞书表里拉出“有订单号但 SKU 为空”的记录
2. 再按店铺分组，到对应千帆后台只读慢查真实完整规格
3. 最后把确认好的规格写回飞书 SKU 列
```

- `plan` 只负责整理缺失 SKU 的订单和店铺资料映射，不会写飞书，也不会修改千帆后台
- `apply` 只负责把已经确认好的真实规格写回飞书，不会碰千帆后台
- SKU 正式查询页固定统一走 `https://ark.xiaohongshu.com/app-order/order/query`，不同店铺只切 Chrome profile，不再为每个店铺单独维护一套页面流程
- 店铺到 Chrome profile 的正式映射固定收敛到 `config/xhs_order_query_profiles.json`；后续新增店铺优先加配置，不要重写主流程
- 千帆后台查到的原始规格，会先按 `config/xhs_order_query_profiles.json` 里的标准化映射转成正式 SKU；没命中映射时才保留原始规格回写
- 这条链路的正式交互主备固定为 `AX -> browser_js -> mouse`，其中 `AX` 是长期主方案，`browser_js` 只作增强或验证，鼠标仅作最后兜底
- 正式窗口绑定固定按“店铺 profile + 统一订单查询页 URL”重绑目标窗口，不依赖用户刚好停留在正确 tab
- 当前 `SKU` 列正式口径优先写标准化后的 SKU，同时保留查询结果里的原始规格文本用于审计和排查
- 涉及千帆后台查询时，默认只允许串行、单店分批、低频执行
- 极度保守口径下，默认一轮不超过 5 单；一轮结束后必须停一下，再决定是否继续下一轮
- 搜索之间不能使用固定时间间隔，必须保持不规则停顿，避免形成明显的机器节奏
- 由于 Chrome 正在使用中的真实资料会被浏览器锁住，这条链路默认继续复用你当前正在用的 Chrome 资料和页面状态执行，不另外复制一套长期资料
- 在 Codex 里使用这个工作区时，如果你直接说“帮我把好评表里的订单 SKU 补齐”或类似意思，助手应直接按这套流程执行，不要把命令行甩给你

## 飞书已上评同步

当前工作区已经新增“好评表已上评自动同步”能力，对应脚本是 `scripts/sync_feishu_review_status.py`。
正式主跑/补跑驱动固定走：

```bash
python3 scripts/run_review_status_sync.py --mode main
python3 scripts/run_review_status_sync.py --mode retry
bash scripts/install_review_status_launchagent.sh
```

这条能力的正式口径固定是：

```text
1. 先从飞书表里拉出“上评日期早于今天、且已上评未勾选”的记录
2. 按店铺分组，到对应千帆评价管理页按日期范围搜索并全部导出
3. 用导出 CSV 里的订单号回写飞书，把命中的订单勾选到“已上评”
```

- 千帆侧默认只走“评价管理页按日期范围导出”这一条主链路，不拿“逐单综合搜索”做备用方案
- 导出交互正式默认先走 `AX`：复用现有 Chrome 店铺资料打开评价页后，通过无鼠标的可访问性控件操作完成日期填写、搜索、全部导出，正常路径不抢鼠标
- 点完“全部导出”后，会先给 `60` 秒确认下载是否真的开始；如果首轮明显没开始，会先关掉本轮页面，重新打开干净页面再按 `AX` 重跑一轮
- 只有“首轮 AX 没开始导出 + 重开页面后再跑仍失败”时，才会降级到现有鼠标流兜底；因此正式链路现在是“AX -> 重开后再试 AX -> 鼠标兜底”
- `browser_js` 仍保留在脚本里作为显式验证模式，但不再作为这条正式定时链路的默认主方案，因为真实多店铺资料下的 AppleScript JS 行为不够稳定
- 默认只处理飞书表里的 `已上评` 字段，不在千帆后台做任何写操作
- 导出文件默认先到桌面找，桌面没有新的，再去 `Downloads` 找
- 导出文件列名口径固定按 `订单id` 匹配飞书 `订单号`
- 定时任务默认按 `14:00` 主跑；只有主跑失败时，`14:20` 才会自动补跑一次。正式安装入口固定是 `bash scripts/install_review_status_launchagent.sh`
- 如果主跑只是查到漏上评，会直接通知结果，不再为了漏上评再补跑
- 本机定时任务固定锁定到带 `pyautogui` 的 Python 3.11，并在安装时把 `PATH` 和 `REVIEW_STATUS_PYTHON_BIN` 一起写进 `launchd` 配置，避免 macOS 默认系统 Python 缺依赖导致静默失败
- 这里保留 Python 3.11 + `pyautogui` 不是因为它还是主链路，而是为了鼠标兜底可随时接管
- 这条链路即使从 `current` 正式入口运行，计划文件、状态文件和导出缓存也固定写回工作区根目录共享 `runtime/`，不在发布快照里另起一套 `current/runtime`
- 页面就算被关掉，正式任务也会先复用对应店铺 Chrome 资料重新打开评价管理页，再走搜索和导出
- 正式链路不再假设“上一次打开的评价页窗口还在”：每轮都会先在所有 `Google Chrome` 主进程里重新扫描可见窗口，按目标 URL 和店铺文本重绑正确窗口；如果旧窗口被手动关掉，会先自己重开再继续
- 如果本机同时跑着多套 `Google Chrome` 主进程，正式链路会优先按“目标页面 URL + 窗口标题/页面文本里的店铺名”选中正确窗口，不再简单取 `pgrep` 返回的第一个 Chrome 进程
- 如果 Chrome 禁用了“Apple 事件里执行 JavaScript”，正式链路不会因为页内 JS 不可用而整轮失败；活动蒙层会自动降级到 `AX` 安全按钮兜底，只允许点“关闭 / 取消 / 稍后 / 跳过”这类安全控件
- 每轮任务用到的评价导出临时文件，任务结束后会自动删除，不在桌面和运行目录长期残留
- 每轮任务结束后，只会按“任务开始前后窗口集合差异”去关闭本轮新开的任务窗口，不再盲关同 URL 页面；如果任务前窗口快照缺失，会明确放弃自动关窗，避免误关你原来就在用的 Chrome 窗口。关窗失败会记明残留窗口，不再假装成功
- 如果全部命中并成功回写，就不需要额外打扰用户；如果有订单没找到、导出失败、回写失败或页面异常，必须明确通知，不能静默失败
- 涉及千帆后台时，依然继续复用 [docs/xhs_qianfan_safety.md](/Users/luogic/Code/运营自动化/docs/xhs_qianfan_safety.md) 和 [config/xhs_qianfan_guardrails.json](/Users/luogic/Code/运营自动化/config/xhs_qianfan_guardrails.json) 里的极度保守口径
- 在 Codex 里使用这个工作区时，如果你直接说“帮我同步已上评”或类似意思，助手应直接按这套流程执行，不要再临时发明别的链路

## 改名后的回滚口径

- `releases/` 里改名前生成的历史版本保留不变，只用于审计和极端兜底
- 改名完成后会再发一个新正式版本，作为 `运营自动化` 的首个稳定基线
- 后续日常回滚优先只回滚到改名后的正式版本

## 跨工作区协作规则

- 当前工作区以后如果依赖别的工作区，只能依赖对方正式入口
- 不允许默认连接仓库镜像、临时副本、worktree、历史目录、手工复制目录或聊天里提到的随手路径
- 新增协作规则时，优先修改仓库文档和脚本，不要只留在聊天里

这些规则已经同步写入：

- [AGENTS.md](/Users/luogic/Code/运营自动化/AGENTS.md)
- [config/workspace_governance.json](/Users/luogic/Code/运营自动化/config/workspace_governance.json)
- [docs/workspace_maintenance.md](/Users/luogic/Code/运营自动化/docs/workspace_maintenance.md)
- [scripts/validate_workspace_governance.py](/Users/luogic/Code/运营自动化/scripts/validate_workspace_governance.py)
