# 交接文档（新对话先读）

最后更新：2026-11-26。写给接手的 Claude 或 Codex。详细验证记录见 `docs/progress-claude.md` 和 `docs/progress-codex.md`。

## 一句话现状

M1–M4 已完成并推送到 GitHub `main`。系统能完整运行：上传、审核、发布、下架、索引、课程内检索、演示摘录问答、云端生成问答、引用抽屉、问答日志和统计页。**下一步是 M5 论文实验，当前卡在等实验资料**：用户会把 `evaluation/materials-brief.md` 交给 ChatGPT 生成 24 份资料，再把输出交给我们处理。

## 里程碑

| 里程碑 | 内容 | 状态 |
| --- | --- | --- |
| M1 | 骨架、登录会话、用户与课程管理、云端模型验证 | 完成 |
| M2 | 上传、审核、驳回、下架、下载，三角色权限 | 完成，浏览器三账号联调 |
| M3 | PDF/DOCX/TXT 解析、切块、嵌入、索引进程 | 完成，真实模型离线验证 |
| M4 | 检索、演示/云端问答、引用、日志、统计、限流 | 完成，演示和云端模式都联调 |
| M5 | 资料与题集、调参、对照实验、消融、人工评分 | **未开始，等资料** |
| M6 | 本地演示准备、README、答辩录屏 | 未开始 |

测试基线（2026-11-26）：后端 pytest 255 项通过，scripts unittest 60 项通过，前端 `npm run build` 通过。

## 关键结论（不要推翻，除非有新证据）

- **生成模型基线**：百炼北京区 `qwen-flash-2025-07-28` + 提示词 `spike-v2`。M1 人工评分：结构 20/20，可答题答对且引用有支撑 15/15，无答案题拒答 4/5（NET-006 失败，留作回归用例），补充无答案题 15/15。详见 `docs/decisions.md`。
- **后端问答提示词**复制自 `scripts/spike_llm.py` 的 `spike-v2`，`backend/tests/test_qa_prompt.py` 断言两者一致。改一边必须同步另一边。
- **切块配置**：350 token，重叠 50，标识 `v1:350:50`。嵌入模型标识 `BAAI/bge-small-zh-v1.5@7999e1d…`。检索只用与当前配置一致的片段。
- **检索参数（临时）**：Top-K 5，证据门槛 `RETRIEVAL_MIN_SIMILARITY=0.40`。**0.40 可能偏低**：联调时"实验报告迟交怎么扣分？"在相关资料下架后，仍召回了两条不相关片段（0.4047、0.4016）。M5 用验证集正式调参。
- 下架资源保留片段，检索时按审核状态过滤；返回前会再确认引用仍可见。

## 环境与启动

| 项目 | 值 |
| --- | --- |
| 仓库 | `D:\codex\scf`，远程 `origin` = `github.com/ykzzzzzzz/edu-rag-resource-management` |
| Python | `E:\scf-env\venv\Scripts\python.exe` |
| PostgreSQL | 16.15 + pgvector 0.8.6，`127.0.0.1:55432`，开发库 `scf`，测试库 `scf_test`，账号 `scf_admin` |
| 数据库密码 | `E:\scf-env\postgres-init-password.txt`（不要输出） |
| 演示账号 | `admin`、`teacher01`、`student01`，密码在 `data/local/demo-accounts.txt`（不要输出） |
| 模型缓存 | `E:\scf-env\hf-cache` |
| 后端 | `127.0.0.1:8000` |
| 前端 | `127.0.0.1:5173`，`/api/v1` 代理到后端 |

启动顺序（PowerShell 7）：

```powershell
# 1. 数据库（重启电脑后需要；已在运行则跳过）
& 'E:\scf-env\postgres\Library\bin\pg_ctl.exe' -D 'E:\scf-env\pgdata' -l 'E:\scf-env\postgres.log' -o '-h 127.0.0.1 -p 55432' -w start
# 2. 后端（会先执行 alembic upgrade head）
pwsh -File .\scripts\start-api.ps1
# 3. 前端
pwsh -File .\scripts\start-web.ps1
# 4. 索引进程（审核通过的资料要靠它变成"可用于问答"；--once 只处理一项）
pwsh -File .\scripts\start-indexer.ps1 --once
```

注意：

- 后端启动后，嵌入模型在后台加载 46–85 秒，期间 `/qa/ask` 返回 503 `retrieval_warming_up`。
- 用 `Start-Process` 后台启动后端是可靠的。曾有一次用 .NET `ProcessStartInfo` 重定向输出启动后，模型加载失败（503 `retrieval_unavailable`），原因未查明，没能复现。
- 云端联调：只给单个后端进程设 `QA_MODE=cloud`，`.env` 保持 `demo`。
- 迁移开发库前先备份：

```powershell
# 从 .env 读 DATABASE_URL 拆出用户和密码，设到 $env:PGPASSWORD 后：
& 'E:\scf-env\postgres\Library\bin\pg_dump.exe' -h 127.0.0.1 -p 55432 -U scf_admin -d scf --no-owner -f data\local\scf_before_XXXX.sql
# 用完 Remove-Item Env:PGPASSWORD
```

## 开发库现有数据

迁移版本 `0004_qa_logs`。现在**只有 1 个可检索的片段**（"M3 索引联调样例"，数据库原理）。另有已下架的"网络实验须知""训练营作业规则""事务隔离性讲义"和待审核的"待驳回资料"，都是联调遗留。`qa_logs` 有 20 条联调记录。M5 正式实验前，建议征得用户同意后清理这些联调数据，或者另建一个实验库。

## 代码地图

| 位置 | 内容 |
| --- | --- |
| `backend/app/routers/` | `auth`、`admin_users`、`courses`、`resources`（含管理员审核）、`qa`（问答、引用、统计、日志）、`system` |
| `backend/app/uploads.py` | 流式上传、按内容校验 PDF/DOCX/TXT、存储路径 |
| `backend/app/index_documents.py` | 解析与按 token 切块，保留页、段、行定位 |
| `backend/app/index_worker.py` | 独立索引进程：任务令牌、租期、可终止的子进程 |
| `backend/app/embeddings.py` | 共享的模型加载、查询嵌入、后台预加载 |
| `backend/app/qa_service.py` | 检索、门槛、演示摘录、云端生成、引用复核、写日志 |
| `backend/app/qa_prompt.py`、`llm_client.py` | spike-v2 提示词与校验、云端 HTTP 调用与错误分类 |
| `backend/migrations/versions/` | 0001 用户课程会话，0002 资源与审核，0003 切块，0004 问答日志 |
| `frontend/src/views/` | 登录、资源浏览与详情、我的资源、审核管理、问答、问答日志、统计 |
| `scripts/spike_llm.py` | M1 模型验证脚本，带 `--prompt-version`、`--interval` |
| `scripts/seed.py` | 幂等创建演示账号和课程 |
| `evaluation/spike/` | M1 题集、补充题和试跑结果 |

## M5 下一步

1. **等资料。** 用户把 `evaluation/materials-brief.md` 发给 ChatGPT，GPT 分批输出 24 份资料（3 门课 × 8 份），每份带"关键事实"原句。用户把全部输出交回。
2. **转换资料。** 写脚本解析 GPT 的输出格式（`=== 资料开始 ===` 等标记），生成真正的 PDF（按 `【分页】` 分页，需带文本层）、DOCX、TXT。检查：字数、格式、事实表与正文是否一致、"关键事实"原句能否在正文中找到。保存来源、授权（自编、AI 生成）和版本。
3. **入库。** 通过正式接口用 `teacher01` 上传、`admin` 审核，运行索引进程，确认全部 `ready`。记录每份资料的稳定编号（如 `DB-01`）到数据库 ID 的映射。
4. **出题。** 起草验证集 24 题（18 可答、6 无答案）和测试集 60 题（45 可答、15 无答案）。可答题标注知识类型（`general` / `institutional`）和难度（`direct` / `paraphrase_multi`），金标准位置标到页或段。由用户审核定稿，定稿后不再改。
5. **写实验脚本。** `scripts/run_evaluation.py`（`baseline` / `rag` 两种模式，可覆盖 Top-K、门槛、切块配置）、`scripts/blind_sheet.py`（盲评表）、`scripts/reindex.py`（切块长度消融）。指标定义见 `DEVELOPMENT_PLAN.md` 第 9.3 节。
6. **评分规则** `evaluation/rubric.md`，评分开始前定稿。第二评分人由用户找同学担任，独立评 20 题。
7. 云端实验费用估算在 ¥0.05 以内，运行前告诉用户。

## 已知问题与待办

- `scripts/start-indexer.ps1` 在 Windows PowerShell 5.1 下报错，用 `pwsh`。可以给文件加 UTF-8 BOM 修复。脚本里还写死了 venv 路径。
- 证据门槛 0.40 偏低的迹象，M5 调参。
- 云端错误映射（鉴权、余额不足、限流、超时）只有模拟测试。
- 前端上传上限 20 MiB 写死在 `frontend/src/utils/resource.ts`。
- 审核管理页默认只显示"待审核"。
- 统计页每日问答图横轴只标隔天日期。
- `.playwright-mcp/` 未加进 `.gitignore`。
- 没有根目录 `README.md`（M6 必需）。
- 本机测试库密码曾在一次失败诊断中显示过，未轮换。
