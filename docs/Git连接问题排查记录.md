# Git 连接问题排查记录

> 日期：2026-09-07
> 环境：公司 Windows 电脑，项目 `E:\SQS\Projects\Xpp\KnowledgeBase`
> 远端：`git@github.com:xpp726/KnowledgeBase.git`（GitHub 个人仓库，SSH 连接）

---

## 一、问题现象

在项目目录执行 `git pull` 报错：

```
Connection closed by 28.0.0.33 port 22
fatal: Could not read from remote repository.
Please make sure you have the correct access rights
and the repository exists.
```

同一时段内，`git push` 走 HTTPS 曾报 `HTTP 408`（RPC failed / 请求超时）。

## 二、根因分析

两个独立问题叠加，表现都是"连不上远端"：

1. **公司网络对 GitHub 的 SSH 22 端口间歇性干扰**：SSH 握手在 22 端口偶发被重置（`Connection closed`）。TCP 探测 22 端口连通，但 SSH 应用层连接不稳定；HTTPS 推送同样在数据传输阶段超时（408）。
2. **`master` 分支丢失上游跟踪信息**：此前用 `git-filter-repo` 重写仓库历史时，工具会自动移除 `origin` remote；重新 `git remote add origin` 后，分支的上游跟踪（`branch.master.remote/merge`）没有恢复，导致 `git pull` 报 "There is no tracking information for the current branch"。

## 三、解决方案

### 方案 1：SSH 改用 443 端口（绕过 22 端口干扰）

GitHub 官方提供备用 SSH 通道 `ssh.github.com:443`，公司网络下比 22 端口稳定。

在 `~/.ssh/config` 末尾追加：

```ini
# GitHub over 443
Host github.com
    HostName ssh.github.com
    Port 443
    User git
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

接受主机密钥并验证认证（首次连接 443 需要）：

```powershell
ssh -T -o StrictHostKeyChecking=accept-new git@github.com
# 期望输出：Hi xpp726! You've successfully authenticated, but GitHub does not provide shell access.
```

> 注意：首次连接 443 若不加 `StrictHostKeyChecking=accept-new`，非交互终端会卡在主机密钥确认环节，表现为"连接挂起"。

### 方案 2：恢复 master 分支上游跟踪

```powershell
git branch --set-upstream-to=origin/master master
# 期望输出：branch 'master' set up to track 'origin/master'.
```

执行后 `git branch -vv` 应显示 `* master <commit> [origin/master] ...`。

## 四、验证结果

| 检查项 | 命令 | 结果 |
| --- | --- | --- |
| SSH 认证（443 通道） | `ssh -T git@github.com` | ✅ Hi xpp726! |
| 拉取 | `git pull` | ✅ Already up to date |
| 推送 | `git push` | ✅ Everything up-to-date |
| 分支跟踪 | `git branch -vv` | ✅ `master [origin/master]` |

## 五、后续注意事项

1. **家里电脑**：若也遇到 22 端口被切断，复制上文 `~/.ssh/config` 的 GitHub 配置即可；家里网络正常则无需改动。
2. **新机器 clone 项目**：`git clone` 自带分支跟踪，不需要执行方案 2。
3. **执行过历史重写（filter-repo / filter-branch）后**：检查 `git branch -vv` 是否仍显示 `[origin/master]`，丢失则按方案 2 恢复。
4. **HTTPS 推送超时（408）**：属同类网络问题，改用 SSH 通道（22 或 443）即可；如必须用 HTTPS，可调大 `git config http.postBuffer`（本次已配置为 524288000）并指定 `http.version HTTP/1.1` 缓解。
