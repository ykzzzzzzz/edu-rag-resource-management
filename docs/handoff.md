# 交接文档（新对话先读）

最后更新于 2026-11-27。写给接手的 Claude 或 Codex。详细验证记录见 `docs/progress-claude.md` 和 `docs/progress-codex.md`。

## 一句话现状

M1–M4 已完成，用户管理和课程管理页面均已补齐。M5 的 24 份正式资料已通过系统接口导入独立实验库并建好索引，24 道验证题已完成离线调参，60 道独立测试题、评分规则和盲评工具已就绪。下一步由作者对照原件签核金标准，接入云端对照实验与检索消融。

## 里程碑

| 里程碑 | 内容 | 状态 |
| --- | --- | --- |
| M1 | 骨架、登录会话、用户与课程管理、云端模型验证 | 完成 |
| M2 | 上传、审核、驳回、下架、下载，三角色权限 | 完成，浏览器三账号联调 |
| M3 | PDF/DOCX/TXT 解析、切块、嵌入、索引进程 | 完成，真实模型离线验证 |
| M4 | 检索、演示/云端问答、引用、日志、统计、限流 | 完成，演示和云端模式都联调 |
| M5 | 资料与题集、调参、对照实验、消融、人工评分 | 已完成资料索引、24/60 题集、验证集检索调参、评分规则及盲评工具；待人工签核、对照实验、消融与盲评 |
| M6 | 本地演示准备、README、答辩录屏 | 未开始 |

测试基线（2026-11-26）：后端 pytest 255 项通过，scripts unittest 60 项通过，前端 `npm run build` 通过。

## 关键结论（不要推翻，除非有新证据）

- **生成模型基线**：百炼北京区 `qwen-flash-2025-07-28` + 提示词 `spike-v2`。M1 人工评分：结构 20/20，可答题答对且引用有支撑 15/15，无答案题拒答 4/5（NET-006 失败，留作回归用例），补充无答案题 15/15。详见 `docs/decisions.md`。
- **后端问答提示词**复制自 `scripts/spike_llm.py` 的 `spike-v2`，`backend/tests/test_qa_prompt.py` 断言两者一致。改一边必须同步另一边。
- **切块配置**：350 token，重叠 50，标识 `v1:350:50`。嵌入模型标识 `BAAI/bge-small-zh-v1.5@7999e1d…`。检索只用与当前配置一致的片段。
- **检索参数（临时）**：Top-K 5，证据门槛 `RETRIEVAL_MIN_SIMILARITY=0.40`。**0.40 可能偏低**：联调时"实验报告迟交怎么扣分？"在相关资料下架后，仍召回了两条不相关片段（0.4047、0.4016）。M5 实验按验证集预定规则选出 K=3、门槛 0.65，详见决策记录。网站仍使用临时默认值。
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

启动方式（Windows PowerShell 5.1 和 PowerShell 7 都可以）：

```powershell
# 推荐：一键启动。检查并按需启动数据库，再各开一个窗口运行后端和前端（窗口出错不会自动关闭）。
powershell -File .\scripts\start-all.ps1
# 同时开启索引进程（审核通过的资料靠它变成"可用于问答"）：
powershell -File .\scripts\start-all.ps1 -WithIndexer
```

也可以分别启动：

```powershell
# 1. 数据库（重启电脑后需要；已在运行则跳过）
& 'E:\scf-env\postgres\Library\bin\pg_ctl.exe' -D 'E:\scf-env\pgdata' -l 'E:\scf-env\postgres.log' -o '-h 127.0.0.1 -p 55432' -w start
# 2. 后端（会先执行 alembic upgrade head）
.\scripts\start-api.ps1
# 3. 前端
.\scripts\start-web.ps1
# 4. 索引进程（--once 只处理一项）
.\scripts\start-indexer.ps1 --once
```

三个启动脚本和 `start-all.ps1` 都已加 UTF-8 BOM。此前不带 BOM 时，Windows PowerShell 5.1 会把中文字符串读错而报语法错误，表现为双击或"用 PowerShell 运行"时窗口一秒就关闭。**以后新增含中文的 `.ps1` 文件必须保存为带 BOM 的 UTF-8。**

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

迁移版本 `0004_qa_logs`（2026-11-27 查库确认）。现在**只有 1 个可检索的片段**（"M3 索引联调样例"，数据库原理）。另有已下架的"网络实验须知""训练营作业规则""事务隔离性讲义"和待审核的"待驳回资料"，都是联调遗留。`qa_logs` 有 20 条联调记录。

2026-11-27 联调用户管理和课程管理页面时，新增了两条联调遗留：**账号 `tmp.teacher02`（已停用）**和**课程"联调临时课程"**，实验入库前要一起清理。真实的演示账号只有 `admin`、`teacher01`、`student01`，课程只有"数据库原理""计算机网络""Python 程序设计"。

M5 使用独立实验库 `scf_experiment` 和专用数据库角色 `scf_experiment_app`。2026-11-27 本机验收时，开发库仍有 5 份资料、20 条问答日志、4 个账号和 4 门课程。实验库有 24 份正式资料、147 个 512 维片段，问答日志 0 条。

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
| `frontend/src/views/` | 登录、资源浏览与详情、我的资源、审核管理、问答、问答日志、统计、用户管理、课程管理 |
| `scripts/build_materials.py` | 把 `evaluation/course-materials.txt` 转成 `data/samples/materials/` 下的 PDF/DOCX/TXT，并生成清单和关键事实定位 |
| `scripts/setup_experiment.py` | 初始化独立实验库、启动本机实验 API、运行真实离线索引 |
| `scripts/import_experiment_materials.py` | 通过教师上传、管理员审核导入清单，核对原件并保存资料编号到资源 ID 的映射 |
| `scripts/spike_llm.py` | M1 模型验证脚本，带 `--prompt-version`、`--interval` |
| `scripts/seed.py` | 幂等创建演示账号和课程 |
| `evaluation/spike/` | M1 题集、补充题和试跑结果 |

## M5 下一步

状态（2026-11-27）：正式资料已生成、入库并完成索引。验证集已用于离线选参，独立测试题及评分规则已编制。

1. ~~**等资料。**~~ **已完成。** 24 份资料由 AI 生成，保存在 `evaluation/course-materials.txt`，已通过格式和事实检查（250 条关键事实原句都能在正文中找到）。来源写为"由 AI 辅助生成的虚构教学资料"，授权为"自编虚构内容，可公开分发"。论文里写具体是哪个 AI 时，请向用户确认（资料实际由 Codex 写成）。
2. ~~**转换资料。**~~ **已完成。** `python -I scripts/build_materials.py` 生成 `data/samples/materials/{DB,NET,PY}/` 下 24 个真实文件（9 份 PDF、9 份 DOCX、6 份 TXT），以及 `manifest.json`（含 sha256、来源、授权）和 `key_facts.jsonl`（250 条金标准定位，直接用后端的 `extract_units` 计算）。PDF 用 reportlab 生成并嵌入宋体，依赖在 `scripts/requirements-materials.txt`，不在后端依赖里。已验证：24 个文件都通过后端 `validate_content`，脚本测试 98 项通过，重复运行产物逐字节一致。已知：9 份 PDF 共有 13 行以标点开头（CJK 换行没有避头标点），不影响解析。
3. **入库已完成。** 24 份资料经教师上传、送审、管理员审核、真实离线索引后全部 `ready`。重跑导入后资源编号映射和审核记录均未重复。映射位于 `data/local/experiment/resource_map.json`，独立库和上传目录的复现命令见下方。
4. **题集与人工核对。** `evaluation/validation.jsonl` 24 题（18/6），`evaluation/test.jsonl` 60 题（45/15），已按正式资料核对位置并留存版本指纹。作者须对照原件签核，尤其留意 21 道无答案题的提问范围。
5. **离线校准已完成。** 实验配置 K=3、相似度 ≥0.65、切块 350/50。完整结果在 `evaluation/results/retrieval_calibration.json`。复跑时从仓库根目录运行 `python -I scripts/calibrate_retrieval.py --output data/local/experiment/calibration-repeat.json`，指定新的结果文件名。正式测试题仅用于后续测量。
6. **实验工具与评分。** 评分规则见 `evaluation/rubric.md`。`scripts/blind_sheet.py create` 生成双人匿名卷，`restore` 还原得分及一致率。待实现 `scripts/run_evaluation.py` 和切块消融 `scripts/reindex.py`。真实回答生成后由作者与同学分别评分。
7. 云端实验费用估算在 ¥0.05 以内，运行前告诉用户。

### 复现实验入库

从仓库根目录运行。`init` 使用本机管理员创建实验库、启用扩展，然后以独立角色执行迁移并创建演示账号。另开 PowerShell 运行 `serve`，服务监听 `127.0.0.1:8015` 和演示模式。凭据、文件与映射均保存在 Git 忽略的 `data/local/experiment/`。

```powershell
$scfPython = 'E:\scf-env\venv\Scripts\python.exe'
& $scfPython -I scripts/setup_experiment.py init
# 在第二个终端定义同一个 $scfPython 后启动实验 API
& $scfPython -I scripts/setup_experiment.py serve
# 回到第一个终端，通过正式接口导入并索引
& $scfPython -I scripts/import_experiment_materials.py --base-url http://127.0.0.1:8015 --origin http://127.0.0.1:8015 --accounts-file data/local/experiment/demo-accounts.txt --out data/local/experiment/resource_map.json
& $scfPython -I scripts/setup_experiment.py index
```

## 已知问题与待办

- 启动脚本里写死了 venv 路径 `E:\scf-env\venv\Scripts\python.exe`，换机器要改。（PowerShell 5.1 报错的问题已修复，见"环境与启动"。）
- 正式验证集中，实验门槛 0.65 会误拦 6/18 道可答题，论文应呈现取舍。
- 云端错误映射（鉴权、余额不足、限流、超时）只有模拟测试。
- 前端上传上限 20 MiB 写死在 `frontend/src/utils/resource.ts`。
- 审核管理页默认只显示"待审核"。
- 统计页每日问答图横轴只标隔天日期。
- `.playwright-mcp/` 未加进 `.gitignore`。
- 没有根目录 `README.md`（M6 必需）。
- 本机测试库密码曾在一次失败诊断中显示过，未轮换。

## 用户反馈与后续路线图（2026-11-26）

用户看过 demo 后的评价：已有雏形，**功能数量偏少，界面太简陋**。用户明确要求：**先保证 demo 的主要功能正常开发完成，再做美化。** 下面是排好顺序的计划，尚未开工，开工前先和用户确认范围。

| 顺序 | 事项 | 说明 |
| --- | --- | --- |
| 1 | M5 实验资料入库与题集 | 24 份正式资料已索引，两套题已编制并完成验证集离线校准 |
| 2 | ~~补全缺失的管理页面~~ **已完成（2026-11-27）** | 用户管理、课程管理两个页面已做并在浏览器联调通过。重名 409、停用自己、降级最后一个管理员、重置密码、停用后会话立即失效都验证过。用户列表在前端切片分页（后端无分页参数） |
| 3 | 补充功能（候选，待用户挑选） | 计划里的 P1：个人问答历史、关键词与语义混合检索、重排。另可考虑：资源详情页的"相关问答"、批量审核、问答结果反馈（有用/没用）、资源版本说明。这些要先和用户确认再做，避免超出论文范围 |
| 4 | M5 实验与 M6 演示准备 | 调参、对照实验、消融、README、答辩录屏 |
| 5 | 前端美化 | 统一设计风格、首页改造、暗色模式、问答页体验、窄屏适配。放在主要功能完成之后，开工前先让用户选风格方向 |

美化时的参照：动手前先读 `frontend/src` 现有组件（Element Plus，M2、M4 页面风格一致），改动要保持现有接口和路由不变。
