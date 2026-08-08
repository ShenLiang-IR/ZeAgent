# 我的工作台审批中心 — 设计文档

日期: 2026-08-02

## 概述

在我工作台页面新增审批中心，将 Agent 发布/审批流程从独立 admin 页面迁移到工作台内嵌 Tab，同时新增中文日历组件。

## 架构

```
WorkspaceDashboard.vue
├── 标题行（我的工作台 + CalendarWidget 右上角）
├── 应用中心（现有快捷卡片，不变）
├── 间隔 (~32px)
└── ApprovalTabs.vue
    ├── Tab: 我的代办（全部）
    ├── Tab: 我提交的审批（非 admin）
    └── Tab: 我的审批（admin）
```

## 后端变更

### 新 API
- `GET /api/admin/agents/my-submissions?status=0,1,2` — 当前用户的提交记录
- WebSocket `/ws/approvals` — 审批状态实时推送

### 修改
- `approve_agent` / `submit_for_review` — 审批操作后广播 WebSocket 消息

## 前端组件

### CalendarWidget.vue
- Element Plus el-calendar 定制，中文，今天高亮，待办日期圆点

### ApprovalTabs.vue
- 基于角色显示不同 Tab（admin: 代办+我的审批，用户: 代办+我的审批）
- 表格展示待办/提交/审批列表
- 与 WebSocket 集成实现实时刷新

## 数据流
```
审批操作 → 后端广播 WS → 前端收到 → 刷新对应列表
WS 断开 → 降级 30s 轮询
```
