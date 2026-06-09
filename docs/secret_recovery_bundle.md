# 私密钥匙灾备说明

适用目录：`/Users/luogic/Code/运营自动化`

## 目标

这份加密包只负责保存“换电脑后还需要重新放回机器里的钥匙类文件”，不负责保存代码、`runtime/` 运行态，也不直接备份 Chrome 店铺整套用户资料。

## 已盘点的真实恢复入口

当前仓库真实需要关心的恢复入口分两类：

### 已纳入加密包

- 共享本机环境文件：`~/.ai-copy.env`
  - 当前仓库已改为从这里读取飞书 `base token`
- GitHub SSH：
  - `~/.ssh/github_pm_bot_kevin_ed25519`
  - `~/.ssh/github_pm_bot_kevin_ed25519.pub`
  - `~/.ssh/config`
  - `~/.ssh/known_hosts*`（可选）
- `lark-cli` 本机认证：
  - `~/.lark-cli/config.json`
  - `~/.lark-cli/cache/auth_login_scopes`（可选）
  - `~/Library/Application Support/lark-cli`

### 已确认但不放进这份加密包

- Chrome 店铺登录态与店铺资料目录：`~/Library/Application Support/Google/Chrome/*`
  - 这是千帆后台访问的真实环境入口，但体积大、包含整套浏览器会话，不适合跟代码仓库一起走 GitHub 加密包
  - 换机时仍需要单独恢复或重新登录
- Python 3.11 与 `pyautogui` 运行环境
  - 这属于运行依赖，不是私密钥匙

## 统一维护入口

- 清单：`scripts/maintenance/secret_recovery_manifest.txt`
- 打包脚本：`scripts/maintenance/build_secret_recovery_bundle.sh`
- 日常刷新：`scripts/maintenance/refresh_secret_recovery_bundle.sh`
- 本机口令安装：`scripts/maintenance/install_secret_recovery_passphrase.sh`

## 口令与输出

- 解密口令文件固定走：
  - `/Users/luogic/Library/Application Support/ai-copy-factory-secrets/secret-recovery-passphrase.txt`
- 最新加密包固定输出到：
  - `recovery/secret-bundles/secret-recovery-bundle-latest.tar.gz.enc`
  - `recovery/secret-bundles/secret-recovery-bundle-latest.tar.gz.enc.sha256`

这两个产物可以进 GitHub；口令文件本身绝不能进 GitHub、日志或文档。

## 每天自动刷新

当前正式口径不是“偶尔手动打一次包”，而是：

1. 本机先放好同一套解密口令文件
2. 每次执行 `bash scripts/github_backup.sh` 时，都会先自动刷新一次加密包
3. `launchd` 的每日 GitHub 自动备份在 `10:00` 触发时，也会先走同样的刷新逻辑
4. 如果 manifest 对应的真实输入没有变化，就不会重复改 `secret-recovery-bundle-latest.tar.gz.enc`

这样以后只要当天自动备份成功，密钥加密包也会跟着一起提交到 GitHub。

## 恢复顺序

以后换电脑时，按这个顺序恢复：

1. 拉取代码仓库
2. 取回 `recovery/secret-bundles/secret-recovery-bundle-latest.tar.gz.enc`
3. 用单独保管的同一套口令解开
4. 按包内 `restore_manifest.tsv` 把钥匙文件放回原路径
5. 再恢复 Chrome 店铺登录态
6. 最后继续恢复 Python 运行环境、自动任务和其他业务依赖

如果后续这个仓库又新增新的私密入口，不要靠聊天记忆，直接把路径补进 `scripts/maintenance/secret_recovery_manifest.txt`。
