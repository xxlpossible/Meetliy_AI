# Meeting Agent 设计系统

## 设计理念：温暖工作室 (Warm Workspace)

为知识工作者打造的精致数字工作空间。融入自然材质色调与编辑排版风格，避免冰冷的技术感。

---

## 🎨 调色板

### 主色（暖石灰 Warm Stone）
| Token | Hex | 用途 |
|-------|-----|------|
| `--color-stone-50` | `#FAF9F7` | 页面背景 |
| `--color-stone-100` | `#F3F1ED` | 卡片背景、输入框 |
| `--color-stone-200` | `#E8E4DC` | 边框、分隔线 |
| `--color-stone-300` | `#D6D0C4` | 次要边框 |
| `--color-stone-400` | `#A89F8C` | 次要文字 |
| `--color-stone-500` | `#787165` | 正文辅助 |
| `--color-stone-600` | `#57534A` | 次要标题 |
| `--color-stone-700` | `#44403A` | 正文 |
| `--color-stone-800` | `#292522` | 主要标题 |
| `--color-stone-900` | `#1C1917` | 强调文字 |

### 品牌色（琥珀暖光 Amber Glow）
| Token | Hex | 用途 |
|-------|-----|------|
| `--color-amber-50` | `#FFFBF0` | 浅底色 |
| `--color-amber-100` | `#FFF3D6` | 标签背景 |
| `--color-amber-200` | `#FFE089` | 次级按钮 |
| `--color-amber-300` | `#FFD046` | 高亮 |
| `--color-amber-400` | `#F5B400` | 主要按钮 |
| `--color-amber-500` | `#D99A00` | 按钮悬浮 |
| `--color-amber-600` | `#B37B00` | 文字链接 |

### 语义色
| Token | Hex | 用途 |
|-------|-----|------|
| `--color-success` | `#10B981` | 完成状态 |
| `--color-error` | `#EF4444` | 错误状态 |
| `--color-warning` | `#F59E0B` | 警告/进行中 |
| `--color-info` | `#3B82F6` | 信息/录音中 |

### 说话人色彩（会议转写专用）
| Speaker | Hex |
|---------|-----|
| Speaker 0 | `#3B82F6` |
| Speaker 1 | `#10B981` |
| Speaker 2 | `#F59E0B` |
| Speaker 3 | `#8B5CF6` |
| Speaker 4 | `#EF4444` |
| Speaker 5 | `#06B6D4` |

---

## 🔤 字体系统

### 字体家族
```css
--font-display: 'Noto Serif SC', 'Source Han Serif CN', serif;  /* 标题 */
--font-body: 'Inter', 'PingFang SC', 'Microsoft YaHei', sans-serif; /* 正文 */
--font-mono: 'JetBrains Mono', 'Consolas', monospace; /* 代码/数据 */
```

### 字号层级
```css
--text-xs: 0.75rem;    /* 12px — 标签、徽章 */
--text-sm: 0.875rem;   /* 14px — 次要文字 */
--text-base: 1rem;     /* 16px — 正文 */
--text-lg: 1.125rem;   /* 18px — 增大正文 */
--text-xl: 1.25rem;    /* 20px — 小标题 */
--text-2xl: 1.5rem;    /* 24px — 卡片标题 */
--text-3xl: 1.875rem;  /* 30px — 页面标题 */
--text-4xl: 2.25rem;   /* 36px — 大标题 */
```

### 字重
```css
--font-normal: 400;
--font-medium: 500;
--font-semibold: 600;
--font-bold: 700;
```

---

## 📐 间距系统

基于 4px 的模数比例：
```css
--space-1: 0.25rem;   /* 4px */
--space-2: 0.5rem;    /* 8px */
--space-3: 0.75rem;   /* 12px */
--space-4: 1rem;      /* 16px */
--space-6: 1.5rem;    /* 24px */
--space-8: 2rem;      /* 32px */
--space-10: 2.5rem;   /* 40px */
--space-12: 3rem;     /* 48px */
--space-16: 4rem;     /* 64px */
--space-20: 5rem;     /* 80px */
```

---

## 🔲 圆角
```css
--radius-sm: 4px;
--radius-md: 8px;
--radius-lg: 12px;
--radius-xl: 16px;
--radius-full: 9999px;
```

---

## 🌑 阴影
```css
--shadow-sm: 0 1px 2px rgba(0,0,0,0.04);
--shadow-md: 0 2px 8px rgba(0,0,0,0.06);
--shadow-lg: 0 4px 16px rgba(0,0,0,0.08);
--shadow-xl: 0 8px 32px rgba(0,0,0,0.12);
```

---

## 🧱 组件规范

### 按钮
- **主要按钮**：琥珀色背景 + 深棕文字 + 圆角8px，hover时微上浮
- **次要按钮**：透明背景 + 边框 + 文字
- **危险按钮**：红色背景 + 白色文字
- **图标按钮**：纯图标，hover显示浅色背景

### 输入框
- 浅色背景，聚焦时琥珀色边框 + 柔光
- 圆角8px，内边距 12px 16px

### 卡片
- 白色背景，圆角12px
- 悬停时阴影加深，轻微上浮

### 状态徽章
- 圆角20px，内边距 4px 12px
- 解析中：蓝色背景白字
- 完成：绿色背景白字
- 错误：红色背景白字

---

## 📱 响应式断点
```css
--breakpoint-sm: 640px;
--breakpoint-md: 768px;
--breakpoint-lg: 1024px;
--breakpoint-xl: 1280px;
```

---

## ✨ 动效规范
```css
--transition-fast: 150ms ease-out;
--transition-normal: 250ms ease-out;
--transition-slow: 400ms ease-out;
```

- 页面过渡：淡入淡出 300ms
- 按钮/卡片悬停：上移 2px + 阴影加深
- 录音中的说话点：脉冲动画 1.5s 无限循环
- 新转写行出现：从下方滑入 200ms
