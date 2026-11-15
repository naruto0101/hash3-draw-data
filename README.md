# 哈希三分开奖数据中转站

这是单独的数据中转仓库，与现有软件和现有 GitHub 仓库分开。

## 初始历史数据

- `data/archive/history.csv`：由用户提供的 10,000 期数据，保持原 CSV 字段和开奖顺序。
- `data/manifest.json`：声明彩种、初始最新期号和增量文件布局。

## 自动更新

- GitHub Actions 通过开奖接口检查最新期号；有新期时按时间分页补齐全部记录。
- 新记录按小时分段写入 `data/updates/YYYY/MM/DD/HH.csv`，较长时间未更新的客户端可以按区间补齐。
- 软件首次使用读取历史数据，之后查看 manifest 并只下载尚未同步的增量分段。
- Actions 使用仓库自带的短期 `GITHUB_TOKEN` 写文件；本地提醒 BAT 的个人授权令牌不会放进公开仓库或 BAT 正文。

仓库地址：<https://github.com/naruto0101/hash3-draw-data>

工作流文件位于 `.github/workflows/sync-draws.yml`，计划每 5 分钟检查一次。GitHub Actions 的定时任务可能延迟；本地提醒工具可在发现最近没有运行记录时请求补跑。

独立客户端软件仍在后续制作中。公开数据仓库只放开奖数据和采集所需的工作流文件，不放个人访问令牌。

