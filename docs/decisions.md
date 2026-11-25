# 设计决策记录

## PostgreSQL 版本与本地运行

本机使用 PostgreSQL 16.15 和 pgvector 0.8.6。PostgreSQL 17 的 EnterpriseDB 安装包下载返回 403，conda-forge 中 PostgreSQL 17 与 pgvector 的依赖也存在冲突。因此，本机通过 conda-forge 安装兼容的 PostgreSQL 16 与 pgvector，保留原计划中的 PostgreSQL 向量检索设计。

安装目录为 `E:\scf-env\postgres`，数据目录为 `E:\scf-env\pgdata`。数据库监听 `127.0.0.1:55432`，数据库名为 `scf`，初始化管理账号为 `scf_admin`。密码保存在本机 `E:\scf-env\postgres-init-password.txt`。

重启电脑后，在 PowerShell 手动启动数据库。

```powershell
$env:PATH = 'E:\scf-env\postgres\Library\bin;' + $env:PATH
& 'E:\scf-env\postgres\Library\bin\pg_ctl.exe' -D 'E:\scf-env\pgdata' -l 'E:\scf-env\postgres.log' -o '-h 127.0.0.1 -p 55432' -w start
```

本机已验证 pgvector 版本及向量距离查询。`.env.example` 中的连接串使用占位密码，项目接入时把实际密码填入本机 `.env`，并对连接串中有特殊含义的密码字符进行 URL 编码。应用如何读取配置将在后端实现时确定。
