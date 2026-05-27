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
