# GitHub 备份说明

## 目标

这个仓库的 GitHub 备份只负责代码、文档、脚本、测试和配置模板，不负责真实业务数据。

## 当前状态

- 当前仓库已经具备手动备份脚本、自动备份脚本、自动巡检脚本、自动安装脚本
- 当前 GitHub SSH 远端：`git@github.com:PM-Bot-Kevin/operations-automation.git`

## 手动备份

```bash
bash scripts/github_backup.sh
```

行为：

- 只允许从 `main` 备份
- 只允许推送到 GitHub SSH 远端
- 如果没有代码改动，不会制造空提交
- 如果有改动，会自动提交并推送到 `origin/main`

## 自动备份

安装命令：

```bash
bash scripts/install_backup_launchagent.sh
```

默认时间：

- 每天 `10:00` 自动备份
- 每天 `10:20` 自动巡检
- 成功不通知
- 失败发本机通知，并在 `.github_backup_logs/` 留日志

## 当前接入口径

1. 远端固定为：

```bash
git@github.com:PM-Bot-Kevin/operations-automation.git
```

2. 首次推送：

```bash
git push -u origin main
```

3. 再安装自动备份任务：

```bash
bash scripts/install_backup_launchagent.sh
```

## 明确禁止进入 GitHub 的内容

- `.env`
- 密钥和凭据
- `runtime/`
- `releases/`
- `current`
- `release-log/`
- 缓存、日志、临时文件

这些规则已经由 `.gitignore`、备份脚本和治理校验共同限制。
