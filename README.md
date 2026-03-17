# 中东冲突 OSINT 每日情报简报

自动化情报报告系统，每天北京时间 9:00 自动更新。

## 数据源 (全部免费)

| 数据 | 来源 | 方法 |
|------|------|------|
| Brent/WTI 油价 | Yahoo Finance | yfinance |
| 黄金价格 | Yahoo Finance | yfinance GC=F |
| USD/CNY 汇率 | Yahoo Finance | yfinance CNY=X |
| A股个股/板块 | 东方财富 | 公开API (无需key) |
| 中东新闻 | Al Jazeera / BBC / Reuters | RSS feedparser |

> 霍尔木兹通航量、VLCC运价等专业数据无免费API，需手动更新模板。

## 部署步骤

### 1. 创建 GitHub 仓库
```bash
git init osint-mideast-report
cd osint-mideast-report
cp -r /path/to/osint-auto-update/* .
cp -r /path/to/osint-auto-update/.github .
git add -A
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/osint-mideast-report.git
git push -u origin main
```

### 2. 启用 GitHub Pages
1. 进入仓库 Settings → Pages
2. Source 选择: `Deploy from a branch`
3. Branch 选择: `main`, 目录选择: `/docs`
4. 保存

### 3. 启用 Actions 权限
1. 进入仓库 Settings → Actions → General
2. Workflow permissions: 选择 `Read and write permissions`
3. 保存

### 4. 手动测试
1. 进入 Actions 页面
2. 点击 `Daily OSINT Update` workflow
3. 点击 `Run workflow`
4. 等待执行完成，访问 `https://YOUR_USERNAME.github.io/osint-mideast-report/`

## 本地测试

```bash
pip install -r requirements.txt
python data/fetch_data.py      # 抓取数据
python generate_report.py      # 生成报告
open docs/index.html           # 预览
```

## 目录结构

```
├── .github/workflows/
│   └── daily-update.yml    ← GitHub Actions 定时任务
├── data/
│   ├── fetch_data.py       ← 数据抓取脚本
│   ├── latest.json         ← 最新数据 (自动生成)
│   └── history.json        ← 历史数据 (自动累积)
├── docs/
│   └── index.html          ← GitHub Pages 发布页面 (自动生成)
├── template.html           ← Jinja2 模板 (手动维护)
├── generate_report.py      ← 报告生成器
├── requirements.txt
└── README.md
```

## 自定义

- 修改 `template.html` 可以调整报告的布局和固定内容
- 修改 `data/fetch_data.py` 中的 `STOCK_LIST` 可以更改监控的A股标的
- 修改 `.github/workflows/daily-update.yml` 中的 cron 可以调整更新时间
- 添加新的 RSS 源: 编辑 `fetch_data.py` 中的 `RSS_FEEDS`
