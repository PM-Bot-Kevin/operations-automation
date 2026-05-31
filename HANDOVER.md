# 运营自动化维护交接

## 一句话口径

这个工作区目前没有业务代码，正式运行口径已经固定为“先治理、后业务”：任何后续新增需求都必须先遵守仓库里的发布、回滚、备份和跨工作区协作规则。

## 日常维护顺序

1. 在 `main` 上开发并提交
2. 先跑治理校验和测试
3. 再执行正式发布
4. 需要时只切 `current` 做回滚
5. 日常代码备份固定推 GitHub，不把真实运行数据推上去

## 常用命令

```bash
python3 scripts/validate_workspace_governance.py
python3 -m unittest discover -s tests
bash scripts/release_workspace.sh --summary "本次变更说明"
bash scripts/rollback_workspace.sh --to <release-id>
python3 scripts/show_release_history.py
bash scripts/github_backup.sh
bash scripts/install_backup_launchagent.sh
```

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
- 正式流程固定分成两段：先 `plan` 拉出缺 SKU 订单和店铺资料映射，再由助手在千帆后台只读慢查真实完整规格，最后用 `apply` 回写飞书。
- 这项能力写回飞书时，`SKU` 列口径固定按千帆后台查到的真实完整规格，不再改写成颜色简写。
- 这项能力的千帆侧执行必须继续遵守风控约束：只允许串行、单店分批、低频查询，搜索之间不能用固定时间间隔，必须保持不规则停顿。
- 极度保守口径下，默认一轮不超过 5 单；一轮结束后必须停一下，再决定是否继续下一轮。
- 由于 Chrome 正在使用中的真实资料会有锁，后续不要强行用独立自动化进程抢占同一套 live profile；优先复用用户当前浏览器会话和页面状态。
- 当前仓库还新增“飞书好评表已上评同步”能力，对应脚本是 `scripts/sync_feishu_review_status.py`。
- 这条能力现在已经迁到本机正式定时链路：主驱动是 `scripts/run_review_status_sync.py`，安装入口固定是 `bash scripts/install_review_status_launchagent.sh`，不再依赖 Codex 心跳任务常驻。
- 这项能力固定先整理“上评日期早于今天且已上评未勾选”的订单，再按店铺去千帆评价管理页导出 CSV，最后按导出里的 `订单id` 回写飞书 `已上评`。
- 这项能力默认不拿“逐单综合搜索订单号”做备用方案；导出链路跑不通就直接报错或通知，不要偷偷切到高频搜索。
- 这项能力的正式交互主方案已经改成 `AX` 无鼠标控件操作：复用用户现有 Chrome 店铺资料打开评价页后，通过可访问性控件完成日期填写、搜索和“全部导出”，正常路径不抢鼠标。
- `browser_js` 仍保留在脚本里作为显式验证模式，但不再作为这条正式定时链路的默认主方案。
- 如果 `AX` 主链路失败，才会降级到现有鼠标流兜底；因此 Python 3.11 和 `pyautogui` 现在是兜底依赖，不再是主链路依赖。
- 导出文件默认先在桌面找，桌面没有新的再去 `Downloads` 找；接住后会另存为稳定文件名，避免被下一轮覆盖。
- 定时任务口径固定为 14:00 主跑；只有主跑失败时，14:20 才补跑一次。
- 如果主跑只是查到漏上评，会直接通知结果，不再为了漏上评再补跑。
- 这条本机定时链路固定锁定到带 `pyautogui` 的 Python 3.11；安装脚本会把 `PATH` 和 `REVIEW_STATUS_PYTHON_BIN` 一起写进 `launchd`，避免系统默认 Python 缺依赖导致任务一启动就失败。
- 页面被关掉不影响这条定时任务，它会先复用对应店铺的 Chrome 资料重新打开评价管理页。
- 这条任务结束后会自动删除本轮评价导出临时文件，不在桌面和运行目录长期残留。
- 这条任务结束后还会尽力自动关闭“本轮自己新开的评价页窗口”：优先按窗口 ID 精确关闭；拿不到可用窗口 ID、且前台仍是任务评价页时，直接用 `AX` 关闭前台任务窗口；再不行才退回按评价页 URL 收尾。关窗失败只记日志，不会把主任务打成失败。
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
- 自动备份默认由 macOS `launchd` 执行
- GitHub 是代码备份，不是真实业务数据备份
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
