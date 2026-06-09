# 运营自动化维护交接

## 一句话口径

这个工作区目前没有业务代码，正式运行口径已经固定为“先治理、后业务”：任何后续新增需求都必须先遵守仓库里的发布、回滚、备份和跨工作区协作规则。

## 日常维护顺序

1. 在 `main` 上开发并提交
2. 先跑治理校验和测试
3. 再执行正式发布
4. 需要时只切 `current` 做回滚
5. 日常代码备份固定推 GitHub，不把真实运行数据推上去

## 新网站长期方案口径

- 以后这个仓库如果新增网站、工作台或内部工具网页，默认先按“站点分型”决定长期运行方案。
- 默认固定先按 `云端正式站 -> 本机正式站 -> 本机权限例外站` 评估，不要每次临时发明一套。
- 能上云的尽量上云，避免用户电脑长期挂越来越多正式服务。
- 只有确实依赖这台 Mac 本机文件、Eagle、桌面软件或本机运行环境时，才允许做成本机正式站。
- 只有明确命中 macOS 权限限制、必须从用户会话拉起才能稳定工作的站，才允许归为本机权限例外站。
- 新网站上线时，必须在维护文档里写清它属于哪一类站点；如果是本机正式站或本机权限例外站，必须同时补自动恢复方案。
- 如果现有 3 类都不合适，必须先说明为什么不合适、为什么必须新增方案，以及对稳定性、维护成本、本机负担的影响；只有得到用户明确确认后，才允许新增第 4 类长期方案。

## 常用命令

```bash
python3 scripts/validate_workspace_governance.py
python3 -m unittest discover -s tests
bash scripts/release_workspace.sh --summary "本次变更说明"
bash scripts/rollback_workspace.sh --to <release-id>
python3 scripts/show_release_history.py
bash scripts/github_backup.sh
bash scripts/install_backup_launchagent.sh
zsh scripts/maintenance/refresh_secret_recovery_bundle.sh
```

## 私密钥匙加密包

- 这个仓库已经接入和 `AI生文工厂` 同口令的私密钥匙加密包方案。
- 正式清单固定看 `scripts/maintenance/secret_recovery_manifest.txt`。
- GitHub 备份前会先自动刷新最新加密包；如果内容没变，不会重复改包。
- 解密口令文件固定是 `/Users/luogic/Library/Application Support/ai-copy-factory-secrets/secret-recovery-passphrase.txt`，不要写进仓库、日志或文档。
- 恢复顺序固定看 [docs/secret_recovery_bundle.md](/Users/luogic/Code/运营自动化/docs/secret_recovery_bundle.md)。

## 已固化业务能力

- 当前仓库已经固化“飞书好评图片导出到桌面”能力，对应脚本是 `scripts/export_feishu_order_images.py`。
- 这个能力的触发口径是自然语言，不要求固定句式。只要用户表达的是“导出某天 / 某段时间的好评、好评图片、图片”，就应该按同一流程执行。
- 默认筛选字段固定看飞书表里的 `上评日期`。
- 默认下载字段固定是 `配图`。
- 默认输出位置固定是桌面，文件名固定为 `订单号_1`、`订单号_2` 这种格式。
- 如果用户是在这个工作区里直接提需求，助手应直接执行，不要先把命令行甩给用户。
- 当前仓库新增“小红书千帆店铺后台访问”能力，对应脚本是 `scripts/xhs_qianfan_access.py`。
- 这项能力默认优先复用用户现有的 Chrome 店铺资料；本机当前已发现多套店铺资料，后续应优先用它们重新打开订单页、售后页等后台页面。
- 这项能力的安全边界固定为只读：默认只允许打开、搜索、查询、读取、导出；未经用户明确允许，不得修改店铺后台数据。
- 这项能力还必须遵守风控约束：在用户浏览器里只做最小操作，尽量减少刷新、重复点击和无关页面跳转，避免形成明显的机械化操作轨迹。
- 千帆相关需求的极度保守执行规则已经单独固化到 `config/xhs_qianfan_guardrails.json` 和 `docs/xhs_qianfan_safety.md`，后续默认直接复用，不要每次重新定策略。
- 当前仓库还新增“飞书好评表缺失 SKU 补齐”能力，对应脚本是 `scripts/fill_feishu_order_skus.py`。
- 这条 SKU 能力现在另外补了一层自动驱动 `scripts/run_sku_fill_auto.py`，只负责自动任务编排；手动 `plan / query / apply` 入口继续保留，不受影响。
- 正式流程固定分成两段：先 `plan` 拉出缺 SKU 订单和店铺资料映射，再由助手在千帆后台只读慢查真实完整规格，最后用 `apply` 回写飞书。
- 自动任务模式下，不允许擅自改“哪些订单该填 SKU”的正式标准；继续按 `订单号` 非空且 `SKU` 为空找单。
- 这条 SKU 链路统一走订单查询页 `https://ark.xiaohongshu.com/app-order/order/query`，不同店铺只切 Chrome profile，不再按店铺拆不同页面流程。
- 店铺和 Chrome profile 的正式映射已经单独固化到 `config/xhs_order_query_profiles.json`；后续新增店铺优先补配置，不要继续往主脚本里堆店铺判断。
- 真实规格写回前，默认先按 `config/xhs_order_query_profiles.json` 里的标准化映射转成正式 SKU；没命中映射时才保留原始规格，避免静默写错。
- 这条 SKU 链路的正式交互主备固定为 `AX -> browser_js -> mouse`：`AX` 是长期主方案，`browser_js` 只是增强或验证，鼠标只作最后兜底。
- 这条 SKU 链路的正式窗口绑定固定按“店铺 profile + 统一订单查询页 URL”重绑目标窗口，不依赖用户当前停留 tab。
- 这项能力写回飞书时，`SKU` 列口径固定优先写标准化后的正式 SKU，同时保留原始规格查询结果用于审计和排查。
- 这项能力的千帆侧执行必须继续遵守风控约束：只允许串行、单店分批、低频查询，搜索之间不能用固定时间间隔，必须保持不规则停顿。
- 极度保守口径下，默认一轮不超过 5 单；一轮结束后必须停一下，再决定是否继续下一轮。
- 由于 Chrome 正在使用中的真实资料会有锁，后续不要强行用独立自动化进程抢占同一套 live profile；优先复用用户当前浏览器会话和页面状态。
- SKU 自动任务如果全部成功，就不单独通知；如果有失败，通知必须写失败总条数和店铺分布。
- 当前仓库还新增“飞书好评表已上评同步”能力，对应脚本是 `scripts/sync_feishu_review_status.py`。
- 这条能力现在已经迁到本机正式定时链路：总编排主驱动是 `scripts/run_review_daily_ops.py`，漏上评子驱动是 `scripts/run_review_status_sync.py`，安装入口固定是 `bash scripts/install_review_status_launchagent.sh`，不再依赖 Codex 心跳任务常驻。
- 这项能力固定先整理“上评日期早于今天且已上评未勾选”的订单，再按店铺去千帆评价管理页导出 CSV，最后按导出里的 `订单id` 回写飞书 `已上评`。
- 这项能力默认不拿“逐单综合搜索订单号”做备用方案；导出链路跑不通就直接报错或通知，不要偷偷切到高频搜索。
- 这项能力的正式交互主方案已经改成 `AX` 无鼠标控件操作：复用用户现有 Chrome 店铺资料打开评价页后，通过可访问性控件完成日期填写、搜索和“全部导出”，正常路径不抢鼠标。
- `browser_js` 仍保留在脚本里作为显式验证模式，但不再作为这条正式定时链路的默认主方案。
- 点完“全部导出”后，正式链路会先给 `60` 秒确认下载是否真的开始；如果首轮明显没开始，会先关掉本轮页面，重新打开干净页面后再按 `AX` 重跑一轮。
- 只有“首轮 AX 没开始导出 + 重开页面后再跑仍失败”时，才会降级到现有鼠标流兜底；因此 Python 3.11 和 `pyautogui` 现在是兜底依赖，不再是主链路依赖。
- 导出文件默认先在桌面找，桌面没有新的再去 `Downloads` 找；接住后会另存为稳定文件名，避免被下一轮覆盖。
- 定时任务口径固定为 14:00 主跑；总编排会先跑漏上评，再跑 SKU 自动填写；只有主跑失败时，14:20 才补跑失败子任务。
- 如果主跑只是查到漏上评，会直接通知结果，不再为了漏上评再补跑。
- 如果同一轮里既有漏上评结果又有 SKU 失败，总编排应优先合并成一条 push，标题固定 `好评漏上评&填sku_自动任务`；如果只有 SKU 失败，标题固定 `好评sku填写_自动任务`。
- 这条本机定时链路固定锁定到带 `pyautogui` 的 Python 3.11；安装脚本会把 `PATH` 和 `REVIEW_STATUS_PYTHON_BIN` 一起写进 `launchd`，避免系统默认 Python 缺依赖导致任务一启动就失败。
- 页面被关掉不影响这条定时任务，它会先复用对应店铺的 Chrome 资料重新打开评价管理页。
- 这条任务不再默认假设“上一次打开的评价页窗口仍然存在”。后续维护时要按“窗口可能被用户手动关掉、切走、覆盖”来理解正式链路：每轮都必须自己重新找窗口、自己重开、自己重绑。
- 当前机器可能同时存在多套 `Google Chrome` 主进程；后续如果千帆链路再出窗口识别问题，先排查是不是绑到了错误的 Chrome 主进程，不要再默认 `pgrep` 的第一个 PID 就是目标实例。
- Chrome 侧如果禁用了“允许 Apple 事件中的 JavaScript”，不能把页内 JS 当唯一能力。正式链路现在已经降级成“JS 能用就用，不能用就退到 AX 安全按钮兜底”，后续不要把这条退路删掉。
- 活动蒙层、公告弹窗这类阻断层，正式口径固定只允许点“关闭 / 取消 / 稍后 / 跳过”这类安全按钮；不要点“去参与 / 去开通 / 去设置 / 确认提交”这类正向 CTA。
- 这条任务结束后会自动删除本轮评价导出临时文件，不在桌面和运行目录长期残留。
- 这条任务现在固定先走 `scripts/xhs_qianfan_session.py` 里的“千帆任务会话”：先记任务前窗口快照，再登记本轮自建窗口；收尾时默认只回收本轮自建窗口，不碰用户原来就开着的页面。
- 如果绑定窗口已经偏离目标页或疑似被用户接管，正式口径是不强关，只记录 cleanup warning，避免误关用户正在看的页面。
- cleanup 结果现在会进入正式状态文件；业务结果单独落 `business_status`，收尾结果单独落 `cleanup_status`，页面没关上只记 warning，不把任务通知成失败。
- 当前仓库另外新增了独立窗口守卫小工具 `Qianfan Window Guard`：扩展目录固定是 `chrome_extensions/qianfan_window_guard`，检查脚本固定是 `scripts/check_qianfan_window_guard.py`，使用说明固定看 `docs/qianfan_window_guard.md`。
- 后续如果问题落在“自己开的窗口没有自己关”，先检查目标 profile 是否已加载这套本地 unpacked 扩展；这一步优先级高于继续追加新的 AppleScript 猜测逻辑。
- `scripts/xhs_qianfan_session.py` 目前仍是现有业务脚本里的过渡收尾层，但不再视为唯一长期关窗主线；后续共用能力应逐步向窗口守卫收敛。
- 现有千帆任务、后续新增千帆任务、以及后续新接入的店铺 profile，默认都要接到这套公共关页能力上；禁止继续各自维护一套独立的关窗逻辑。
- 这条任务即使通过 `current` 正式入口执行，计划文件、状态文件和导出缓存也必须继续写回工作区根目录共享 `runtime/`，不要在发布快照里生成另一套 `current/runtime`。
- 这条已上评同步链路的千帆侧执行同样必须遵守极度保守风控规则：只做最小操作、只走导出链路、保持低频和不规则停顿。

## 临时产物规则

- `.artifacts/` 是设计草图、页面快照、临时 HTML 产物目录，只用于本地排查和比对，不进 Git。
- `.playwright-mcp/` 是浏览器自动化留下的页面快照和控制台日志目录，只用于调试，不进 Git。
- 根目录不应长期堆放截图；如果临时生成了截图，统一收敛到 `.artifacts/` 下再忽略。

## 发布规则

- 发布前会自动先跑 `python3 scripts/validate_workspace_governance.py`
- 正式版本写入 `releases/<release-id>/`
- `current` 永远只指向一个正式版本
- `runtime/` 只留真实运行数据和日志，不跟随发布切换
- `release-log/releases.jsonl` 记录发布和回滚

## 回滚规则

- 回滚只切代码版本，不碰 `runtime/`
- 默认回滚到上一版，也支持 `--to <release-id>`
- 回滚后要用 `python3 scripts/show_release_history.py` 看日志确认

## GitHub 备份规则

- 只保留长期主分支 `main`
- GitHub 远端优先只认 SSH
- GitHub 备份和自动安装都要继续对齐 `config/workspace_governance.json` 里的正式 SSH 远端，不要只校验“是不是 GitHub SSH”
- 自动备份默认由 macOS `launchd` 执行
- GitHub 是代码备份，不是真实业务数据备份
- GitHub 自动备份前要先刷新私密钥匙加密包
- `runtime/`、`releases/`、`release-log/`、`.github_backup_logs/`、`current`、`.tmp/`、`.next/`、调试截图、根目录临时导出物，以及名字里带 `secret` / `token` / `credential` 的内容都不能进 GitHub
- 当前 GitHub SSH 远端固定为 `git@github.com:PM-Bot-Kevin/operations-automation.git`

## 改名维护备注

- 这个工作区已从 `上架自动化 / listing-automation` 正式切换到 `运营自动化 / operations-automation`
- 改名前的 `releases/` 历史快照保持只读，不回写新名字
- 改名后的首个正式发布版本是后续常规回滚基线；改名前版本只用于审计和极端兜底

## 跨工作区协作规则

- 以后如果这个工作区要调用别的工作区，只能调用对方正式入口
- 禁止直接接入仓库镜像、临时副本、worktree、历史目录、手工复制目录和聊天路径
- 依赖声明先写入 `config/workspace_governance.json`
- 如果规则需要调整，先改仓库文档和脚本，再开始执行
