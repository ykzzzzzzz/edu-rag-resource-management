# CLAUDE.md

本项目是本科毕业设计：**面向教育机构的 RAG 课程资料管理与问答系统**。教师上传资料，管理员审核发布，学生浏览、下载并提问；系统只依据已发布资料回答并给出可点击的出处。

## 开发前必读（按顺序）

1. `docs/handoff.md`：当前进度、环境、怎么启动、下一步做什么。**新对话先读这份。**
2. `DEVELOPMENT_PLAN.md`：需求、权限、接口契约、数据模型、RAG 流程、论文实验设计和里程碑。实现必须以它为准。
3. `docs/progress-claude.md`：Claude 做过和核对过的工作，区分"已运行验证"和"只读过代码"。
4. `docs/progress-codex.md`：Codex 的进度。用户同时用 Codex 开发，两边靠这两份文件交接。
5. `docs/decisions.md`：设计决策（PostgreSQL 版本、会话、密码哈希、索引、模型选型与评分结论）。
6. 当前任务相关：`evaluation/materials-brief.md`（交给 ChatGPT 生成 M5 实验资料的任务书）。

## 安全与费用（必须遵守）

- **不要读取、打印或提交仓库根目录的 `.env`**。里面有真实的百炼 API 密钥和数据库密码。需要配置值时只读取单个字段，输出前把密钥和连接串打码。
- 不要把以下内容输出到终端或写入任何被 Git 跟踪的文件：`E:\scf-env\postgres-init-password.txt`（数据库密码）、`data/local/demo-accounts.txt`（演示账号密码）、`.env` 中的 `LLM_API_KEY` 和 `DATABASE_URL`。
- **调用云端模型会产生费用**（用户的百炼账号余额很少）。批量调用前先告诉用户次数和估算费用，请求之间保持约 1.2 秒间隔，避免 429。单次问答约 ¥0.0001。
- `.env` 中 `QA_MODE=demo`。需要云端联调时只对单个后端进程临时设置 `QA_MODE=cloud`，不要改 `.env`。
- 在开发库 `scf` 上运行迁移前，先用 `pg_dump` 备份到 `data/local/`（见 `docs/handoff.md`）。
- 提交前扫描暂存内容，确认不含上述密钥和密码。

## Git

- 用户已授权直接提交并推送到 `origin/main`（`https://github.com/ykzzzzzzz/edu-rag-resource-management.git`）。推送前先 `git fetch`，确认没有落后，只做快进推送，不要 force push。
- 这台机器的 git 全局身份是空的。提交时临时传入身份，不要写入配置：
  `git -c user.name=ykzzzzzzz -c user.email=268791822+ykzzzzzzz@users.noreply.github.com commit ...`
- 提交说明用英文、祈使句标题，末尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`。PowerShell 里多行说明要先写到临时文件再用 `git commit -F`，直接传 here-string 会被当成路径。
- `.playwright-mcp/` 是浏览器调试日志，不要提交。

## 环境要点

- Windows 11，Shell 优先用 PowerShell 7（`pwsh`）。`scripts/start-indexer.ps1` 在 Windows PowerShell 5.1 下会因编码报语法错误，必须用 `pwsh -File`。
- Python 虚拟环境：`E:\scf-env\venv\Scripts\python.exe`。运行处理下载数据的 Python 时加 `-I`。
- PostgreSQL 16.15 + pgvector 0.8.6，监听 `127.0.0.1:55432`。开发库 `scf`，测试库 `scf_test`。
- 嵌入模型 `BAAI/bge-small-zh-v1.5`（512 维，固定 revision `7999e1d3359715c523056ef9478215996d62a620`），离线缓存在 `E:\scf-env\hf-cache`。首次加载约 46–85 秒。
- 后端测试只连 `scf_test`，`conftest.py` 会拒绝其他库，并在每次运行时清空重建 schema。测试用假嵌入器和假云端传输层，不加载真实模型，也不联网。

## 常用命令

```powershell
# 后端测试（约 3 分钟）
cd D:\codex\scf\backend; E:\scf-env\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
# 脚本测试
cd D:\codex\scf; E:\scf-env\venv\Scripts\python.exe -I -m unittest discover -s scripts/tests
# 前端构建与类型检查
cd D:\codex\scf\frontend; npm run build
# 用真实模型跑索引测试
$env:SCF_TEST_REAL_EMBEDDINGS='1'; python -m pytest tests/test_index_worker.py
```

启动服务见 `docs/handoff.md`。

## 工作约定

- 子 agent 和 Codex 的报告要自己核对：重跑测试、读关键代码、查数据库，不要直接采信报告里的数字。
- 汇报时区分"亲自运行过"和"只读过代码"，给出实际的测试数量，没验证的要明说。
- 用中文和用户交流，说话直接、简短。
- 改动 `DEVELOPMENT_PLAN.md`、`.gitignore` 或删除数据前先问用户。

## 开发记录必须随改动更新

用户同时用 Claude 和 Codex 开发，两边只靠文档交接。记录没更新，另一方就会重复开发，或在过时的状态上继续改。

**开工前**：先读 `docs/handoff.md`、`docs/progress-claude.md`、`docs/progress-codex.md`，确认要做的事有没有人已经做过或正在做。发现记录和代码、数据库的实际状态不一致时，先以实际状态为准，把记录改正，再开始开发。

**每完成或更新一部分功能后，在同一次提交里更新对应的记录**，不要攒到里程碑结束再补：

| 发生了什么 | 必须更新 |
| --- | --- |
| 完成或修改了一个功能、修了一个 bug | `docs/progress-claude.md`：做了什么、运行过哪些验证（附实际测试数量）、哪些没验证 |
| 当前状态、下一步、已知问题有变化 | `docs/handoff.md` 的"一句话现状""里程碑""下一步""已知问题与待办" |
| 数据库迁移或开发库数据有变化 | `docs/handoff.md` 的"开发库现有数据"，写明迁移版本和备份文件 |
| 新的设计取舍、参数选择、模型或实验结论 | `docs/decisions.md` |
| 启动方式、命令、环境、必读文档有变化 | `CLAUDE.md` 和 `docs/handoff.md` 的"环境与启动" |
| 核对了 Codex 或子 agent 的工作 | `docs/progress-claude.md`，写明核对方式和结果 |

要求：

- 记录里写清最后更新日期。已完成的待办要删掉或标为完成，不要只追加新内容，让旧的说法留在文件里。
- 只写亲自确认过的事实。只读过代码、或来自他人报告的内容要注明。
- `docs/progress-codex.md` 由 Codex 维护，Claude 不改它的内容。发现其中有过时或错误的说法，写进 `docs/progress-claude.md` 并告诉用户。
- 一次工作结束前，检查以上文件是否都已更新，再提交推送。
