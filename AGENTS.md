# 校园网登录助手 - 开发指南

## Git 提交规范

每次代码修改完成后，按以下流程提交：

### 提交前检查清单
1. 代码可运行: `python -c "from main import main; print('OK')"`
2. 不包含调试输出（移除 print 调试语句）
3. 不包含明文密码或敏感信息
4. 不提交临时文件/分析文件

### Commit Message 格式
- `feat: 新功能` — 新增模块、功能
- `fix: 修复问题` — 修复 Bug
- `refactor: 重构` — 代码重构、优化
- `docs: 文档` — 文档更新
- `chore: 杂项` — 配置、构建等
- `perf: 性能` — 性能优化

### 提交流程
```powershell
# 1. 查看变更
git status

# 2. 暂存文件
git add <文件路径>

# 3. 提交
git commit -m "feat: 简短的描述"

# 4. 推送
git push origin master
```

### 分支命名
功能开发用前缀 `codex/`:
- `codex/network-monitor`
- `codex/login-module`
- 等

## 项目说明
校园网自动登录助手 - Python 实现的 Windows 后台驻留工具。
