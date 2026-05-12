# 南方航空新型渠道合作客户信息收集系统

这是一个基于 Streamlit 的本地客户信息收集与内部客户数据看板系统。

## 功能

- 合作客户分步骤填报
- 客户需求信息确认与提交
- SQLite 本地数据库保存
- 南航内部后台查看客户记录
- 客户记录筛选、详情查看、删除
- CSV / JSON 导出

## 运行方式

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 本地数据

客户数据默认保存在：

```text
data/customer_records.db
```

`data/` 目录已加入 `.gitignore`，请不要把真实客户数据上传到 GitHub。

## 后台访问码

本地演示访问码：

```text
csair123
```

该访问码仅用于本地演示，不应作为正式安全机制。
