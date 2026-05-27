# 发布与回滚说明

## 正式发布

```bash
bash scripts/release_workspace.sh --summary "本次变更说明"
```

发布脚本会自动执行：

1. `python3 scripts/validate_workspace_governance.py`
2. 校验当前分支是 `main`
3. 校验工作区干净，正式版本只发布已提交代码
4. 把 `HEAD` 打包到 `releases/<release-id>/`
5. 切换 `current`
6. 追加 `release-log/releases.jsonl`

## 回滚

```bash
bash scripts/rollback_workspace.sh
bash scripts/rollback_workspace.sh --to <release-id>
```

回滚规则：

- 默认回滚到上一版
- 只切代码版本，不回滚 `runtime/`
- 会把回滚记录写入 `release-log/releases.jsonl`
- 改名前的历史版本默认只保留作审计和极端兜底；日常回滚优先选择改名后的正式版本

## 查看历史

```bash
python3 scripts/show_release_history.py
```
