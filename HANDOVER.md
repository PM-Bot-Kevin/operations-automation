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
