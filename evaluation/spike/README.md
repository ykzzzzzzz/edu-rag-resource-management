# M1 生成模型技术验证（spike）

本目录是 `scripts/spike_llm.py` 的样例材料与结果目录。脚本只使用 Python 标准库，不需要安装依赖。

## 文件

- `spike_questions.jsonl`：20 组题目，每组 3 个片段。15 组可答，5 组无答案。片段为自编文字，含"本机构特有"的虚构资料（如考核比例、启明书店案例、实验网段）。
- `heldout_unanswerable_draft.jsonl` 为 15 道新增的无答案题草稿，三门课各 5 题。沿用原试跑的证据片段，测量新问题上的拒答表现。复测前请确认每题在所附片段中无法回答，冻结 `spike-v2`，使用 `--questions evaluation/spike/heldout_unanswerable_draft.jsonl --prompt-version spike-v2 --interval 1.2` 和独立的输出路径。结果按新增题单独报告，原有 5 道调试题继续作为回归用例。
- `results/`：运行输出。`*.jsonl` 为逐题结果，`*_summary.json` 为汇总，`*_manual_scoring.csv` 为人工评分模板。

## 环境变量（仅真实调用需要）

| 变量 | 含义 |
| --- | --- |
| `LLM_BASE_URL` | 兼容 Chat Completions 的基地址，不含 `/chat/completions`。百炼使用业务空间专属域名：`https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`，其中 `{WorkspaceId}` 替换为控制台中的业务空间 ID（以控制台为准）；DeepSeek：`https://api.deepseek.com` |
| `LLM_API_KEY` | API 密钥。只从环境变量或 `--env-file` 读取，脚本不会写入任何输出 |
| `LLM_MODEL` | 模型名，例如 `qwen-flash-2025-07-28` 或 `deepseek-flash` |
| `LLM_PROVIDER` | 可选，`bailian` 或 `deepseek`。命令行 `--provider` 优先；都未指定时默认 `bailian` |

注意：通用域名 `dashscope.aliyuncs.com` 官方已通知将于 2026 年 9 月 30 日起进入维护状态，不建议新业务使用，因此示例改为业务空间专属域名。

PowerShell 设置示例（只在当前窗口生效）：

```powershell
$env:LLM_BASE_URL = "<基地址>"
$env:LLM_API_KEY = "<密钥>"
$env:LLM_MODEL = "<模型名>"
```

也可以把这四个键写入一个 `.env` 文件，用 `--env-file` 指定（格式为 `KEY=VALUE`，支持首尾引号，`#` 开头为注释）。只读取上表中的键，其他键忽略。**已经存在的环境变量优先，不会被 `.env` 覆盖。** 脚本只会报告缺少哪些键，不会打印 `.env` 的任何内容。


## 离线 mock 运行（无需密钥，不联网）

```powershell
E:\scf-env\venv\Scripts\python.exe D:\codex\scf\scripts\spike_llm.py --mock --out D:\codex\scf\evaluation\spike\results\mock_demo.jsonl
```

mock 结果只用于演示校验逻辑，不代表任何模型，不得用于论文。

## 单元测试

```powershell
E:\scf-env\venv\Scripts\python.exe -m unittest discover -s D:\codex\scf\scripts\tests -v
```

## 真实验证（拿到密钥后运行，本次未执行）

先运行首选模型（百炼）：

```powershell
E:\scf-env\venv\Scripts\python.exe D:\codex\scf\scripts\spike_llm.py --provider bailian --out D:\codex\scf\evaluation\spike\results\bailian_run1.jsonl
```

使用仓库根目录的 `.env` 文件（推荐，不必在命令行里写密钥）：

```powershell
E:\scf-env\venv\Scripts\python.exe D:\codex\scf\scripts\spike_llm.py --env-file ..\..\.env --provider bailian --out D:\codex\scf\evaluation\spike\results\bailian_run1.jsonl
```

需要比较备选时运行 DeepSeek（`.env` 中的 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 要换成 DeepSeek 的地址、密钥和模型名）：

```powershell
E:\scf-env\venv\Scripts\python.exe D:\codex\scf\scripts\spike_llm.py --env-file ..\..\.env --provider deepseek --out D:\codex\scf\evaluation\spike\results\deepseek_run1.jsonl
```

可选参数：

- `--limit N`：只跑前 N 题。
- `--temperature`：默认 0.1。
- `--timeout SECONDS`：单题总时限，默认 45 秒。超时的题记为 `timeout`（对应 504），不自动重试。
- `--env-file PATH`：读取 `.env` 中的 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_PROVIDER`。已存在的环境变量优先。

真实运行会产生费用。

逐题 JSONL 的 `upstream_error_message` 字段记录服务商返回的错误信息，最多 300 字符，密钥已替换为 `[已隐藏]`。请求头（含 Authorization）不会被记录。若返回 400，可从该字段判断是哪个参数被拒绝，例如 `enable_thinking` 是否被北京区接口接受，目前尚未验证。

运行后请人工对照原文，填写 `*_manual_scoring.csv` 的"答对?"和"引用能支撑?"两列。
