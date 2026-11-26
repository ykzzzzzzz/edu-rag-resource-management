# 设计决策记录

## M3 文档切块与索引任务

索引进程按发布时间认领已发布的待索引资料，写入任务令牌和到期时间。解析和嵌入运行在可终止的子进程，模型加载后在该进程中复用。发布状态、任务令牌与租期均通过检查时，才在同一事务内替换目标模型和切块配置的片段，并将资源置为 `ready`。下架或超时会使旧任务失效，重试保留其他版本的片段。

PDF 按页分组，DOCX 读取正文段落，TXT 按原始行定位。位置从 1 开始，空白页或段落保留其编号间隔。默认切块目标为 350 token，重叠 50 token，并优先沿段落或句末断开。切块前核对模型长度上限，写库时固定 Hugging Face 模型版本和切块配置。为限制解析和嵌入的内存占用，每份文档最多索引 100 万个提取字符及 4096 个片段。PDF 页数和 DOCX 解包体积另有限制。

先配置仓库根目录的 `.env`，数据库迁移完成后在项目根目录运行 `powershell -File .\scripts\start-indexer.ps1`。传入 `--once` 可只处理一项任务。索引进程只从 `HF_HOME` 下的本地模型缓存加载模型。未配置此项时使用 Hugging Face 默认缓存目录。

## PostgreSQL 版本与本地运行

本机使用 PostgreSQL 16.15 和 pgvector 0.8.6。PostgreSQL 17 的 EnterpriseDB 安装包下载返回 403，conda-forge 中 PostgreSQL 17 与 pgvector 的依赖也存在冲突。因此，本机通过 conda-forge 安装兼容的 PostgreSQL 16 与 pgvector，保留原计划中的 PostgreSQL 向量检索设计。

安装目录为 `E:\scf-env\postgres`，数据目录为 `E:\scf-env\pgdata`。数据库监听 `127.0.0.1:55432`，数据库名为 `scf`，初始化管理账号为 `scf_admin`。密码保存在本机 `E:\scf-env\postgres-init-password.txt`。

重启电脑后，在 PowerShell 手动启动数据库。

```powershell
$env:PATH = 'E:\scf-env\postgres\Library\bin;' + $env:PATH
& 'E:\scf-env\postgres\Library\bin\pg_ctl.exe' -D 'E:\scf-env\pgdata' -l 'E:\scf-env\postgres.log' -o '-h 127.0.0.1 -p 55432' -w start
```

本机已验证 pgvector 版本及向量距离查询。`.env.example` 中的连接串使用占位密码，项目接入时把实际密码填入本机 `.env`，并对连接串中有特殊含义的密码字符进行 URL 编码。应用如何读取配置将在后端实现时确定。

## 会话方式与令牌哈希

问题：浏览器登录后，API 用什么方式识别身份，服务端如何保存凭据。

备选方案：
1. 服务端会话，Cookie 保存随机令牌，数据库保存令牌的哈希。
2. JWT 无状态令牌，由服务端签名，不在数据库保存。
3. 服务端会话，数据库保存明文令牌。

选择：方案 1。Cookie 设置 `HttpOnly`、`SameSite=Lax`，默认有效 8 小时，HTTPS 部署时启用 `Secure`。令牌由 `secrets.token_urlsafe(32)` 生成，数据库 `sessions.token_hash` 保存其 SHA-256 哈希，唯一约束。

理由：本系统需要停用账号、重置密码时立即撤销全部会话。服务端会话可以直接删除行实现撤销，JWT 只能等待过期或维护黑名单。数据库泄露时，哈希无法还原出可用的 Cookie 令牌。令牌本身具有 256 位熵，无需慢哈希，SHA-256 即可。

## 密码哈希算法选择 Argon2id

问题：用户密码在数据库中用什么算法存储。

备选方案：
1. Argon2id，使用 argon2-cffi 默认参数。
2. bcrypt。
3. PBKDF2-SHA256。

选择：方案 1，Argon2id。通过 argon2-cffi 的 `PasswordHasher`，参数沿用库的默认值。

理由：Argon2id 是 Password Hashing Competition 的获胜算法，同时抵抗 GPU 并行破解和侧信道攻击，是 OWASP 密码存储指南推荐的首选。bcrypt 有 72 字节输入上限，且不具备内存硬度。PBKDF2 没有内存硬度，同等成本下更易被 GPU 加速。登录时若哈希参数落后于库的默认值，会自动重新哈希。

## M1 百炼模型试跑与拒答验证

采用 `qwen-flash-2025-07-28` 和 `spike-v2` 作为当前开发基线。经原文和引用复核，v2 达到 M1 模型试跑的三项筛选线。正式论文评估使用后续独立材料和题集。

| 指标 | v1 首轮补跑合并 | v2 完整一轮 |
| --- | --- | --- |
| 结构校验通过 | 20/20 | 20/20 |
| 可答题返回有效回答 | 15/15 | 15/15 |
| 无答案题返回证据不足 | 3/5 | 4/5 |

v2 调用间隔为 1.2 秒，该轮 20 题均完成，未遇到 429。输入 11,159 Token、输出 908 Token，按计划中的单价估算约 ¥0.003。NET-007 的迟交补交问题从作答改为拒答。NET-006 仍把实验内网网段 `10.20.0.0/24` 当成 DHCP 地址段，尽管原文没有提供 DHCP 配置。这说明引用编号通过校验后，仍需核对片段是否支持所述事实。

逐题对照原文与实际引用后，v2 的 15 道可答题全部答对，15 道的引用均支撑关键事实。原 5 道无答案题中，4 道有效拒答，NET-006 判错且引用不支撑答案。结构合规 20/20、答对且引用有支撑 15/15、正确拒答 4/5，分别达到计划中的 18/20、12/15、4/5。v2 根据原试跑题的失败案例调整，这些数字只描述本次试跑。 [逐题评分表](../evaluation/spike/results/bailian_v2_run1_manual_scoring.csv)

补充题复测（冻结 `spike-v2`，间隔 1.2 秒，百炼 `qwen-flash-2025-07-28`）：15 道无答案题全部返回 `insufficient_evidence`，结构校验 15/15，无 429，输入 8,555 Token、输出 480 Token，约 ¥0.002。我逐条读过 15 条拒答文字，没有出现拒答的同时给出资料中没有的事实。

逐题复核了补充题的所附片段与实际拒答，15 题均缺少所问事实，15 条拒答均未引入资料之外的事实。例如，`HOLD-DB-04` 所附片段只有同一客户的 9 月订单数，题目问的是 10 月。`HOLD-NET-02` 的片段只给出一个未标为备用的 DNS 地址。补充题沿用原片段，问法较直接。15/15 仅说明本轮在相同资料的新问题上的表现。NET-006 保留为回归用例，用于检查模型是否把相近数值错配到另一实体或属性。 [补充题汇总](../evaluation/spike/results/bailian_v2_heldout_summary.json) · [补充题草稿](../evaluation/spike/heldout_unanswerable_draft.jsonl)
