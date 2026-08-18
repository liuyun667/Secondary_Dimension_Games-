# 二游毕业指导 · Python 实现

对应《二游毕业指导.md》技术文档的完整可运行 Python 实现。
版本演进见 [CHANGELOG.md](CHANGELOG.md)。

## 技术选型（零依赖优先）

| 层 | 选型 | 说明 |
|---|---|---|
| 存储 | **stdlib `sqlite3`** | 零第三方依赖，开箱即跑；生产可换 MySQL（表结构不变） |
| Web 服务 | **FastAPI + Uvicorn** | 标准选择，自动生成 OpenAPI 文档 |
| OCR | PaddleOCR（可选） | 未安装时用 `text_lines` 模拟输入 |
| 粗分类/实体链接 | 规则 + 别名词典（默认）/ fasttext、BERT（可选） | 词典兜底保证任何环境可跑 |
| 推荐评分 | 规则评分（默认）/ sklearn 随机森林（可选） | `GYZ_USE_RF=1` 启用 |
| LLM 解释 | DeepSeek API（可选，urllib 实现） | 无 key 时用模板文案兜底 |
| 队伍分配 | Hungarian（纯 Python，内置） | §3.7.2 |

## 目录结构

```
二游毕业指导/
├── app/
│   ├── config.py        # 配置（DB 路径、组件开关、LLM）
│   ├── database.py      # sqlite3 存储层（表结构 = 文档 §4）
│   ├── seed.py          # 原神种子数据
│   ├── pipeline.py      # 感知→理解：OCR/分类/实体链接/结构化/analyze
│   ├── engine.py        # 毕业标准合并/毕业度/推荐/队伍/LLM
│   ├── team_alloc.py    # Hungarian + 贪心全局分配
│   ├── schemas.py       # Pydantic 请求/响应模型
│   └── main.py          # FastAPI 入口 + 全部路由
├── scripts/demo.py      # 端到端演示（零依赖，直接跑）
├── tests/test_smoke.py  # 冒烟测试（python tests/test_smoke.py）
└── requirements.txt
```

## 快速开始

```bash
# 1. 零依赖演示（不装任何包，模拟截图全链路）
python scripts/demo.py

# 2. Web 服务（装 FastAPI 后）
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# 文档：http://localhost:8000/docs

# 3. 启用可选重型组件（按需）
$env:GYZ_USE_RF = "1"        # sklearn 随机森林评分（先装 scikit-learn）
$env:DEEPSEEK_API_KEY = "sk-..."   # LLM 真实解释（DeepSeek）
```

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `GYZ_DB_PATH` | `./data/gyz.db` | 数据库路径 |
| `GYZ_SIMULATE_OCR` | `1` | 模拟 OCR（未装 PaddleOCR 时） |
| `GYZ_USE_FASTTEXT` | `0` | 启用 fasttext 粗分类（需安装） |
| `GYZ_USE_RF` | `0` | 启用 sklearn 随机森林评分（需安装） |
| `DEEPSEEK_API_KEY` | 空 | LLM 解释（不填走模板） |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | LLM 端点 |

## 本机环境安装记录（2026 扫描安装）

| 环境 | Python | 已装 | 用途 |
|---|---|---|---|
| 系统 Python `D:\software\Python_en` | 3.14.6 | fastapi 0.141.1 / uvicorn 0.52.3 / pydantic 2.13.4 / numpy 2.5.2 / requests | 默认 Web 服务（已验证可启动） |
| Anaconda `D:\ANA`（base） | 3.12.4 | torch 2.5.1 / scikit-learn 1.9.0 / numpy / pydantic / requests / uvicorn | 备选 |
| Anaconda `D:\ANA\envs\toumanfen` | 3.10.20 | torch 2.7.1 / transformers 5.15.0 / scikit-learn 1.7.2 / fastapi / uvicorn / pydantic（+ paddleocr/paddlepaddle/fasttext 安装中） | **全功能环境**（真实 OCR/分类/评分） |

### 用全功能环境（toumanfen）运行

```powershell
# 全功能环境启动 Web（真实 OCR 等可选组件生效）
& "D:\ANA\envs\toumanfen\python.exe" -m uvicorn app.main:app --port 8000
# 或先激活环境：conda activate toumanfen

# 端到端演示
& "D:\ANA\envs\toumanfen\python.exe" scripts/demo.py
```

> 提示：`D:\ANA\envs\toumanfen\Scripts` 不在 PATH，用 `python -m uvicorn` 调用即可。

## 自动采集插件系统（零翻页）

参考莫娜占卜铺「采集与计算分离」思路：**采集层**（伴生导出工具，自动翻页截图识别）
与**导入层**（本服务，读取导出数据）解耦。浏览器只能只读屏幕、不能模拟按键，
所以"自动采集"走导出文件/剪贴板导入，读屏 OCR 仅作兜底。

| 插件 method | 来源 | 用户参与 |
|---|---|---|
| `file` | 伴生导出工具导出的 JSON（如 Amenona、`tools/auto_export.py`） | 选一次文件，零翻页 |
| `clipboard` | 粘贴导出数据 / 文本行 | 复制+粘贴一次 |
| `sample` | 示例账户 | 点一次按钮 |
| `ocr` | 浏览器读屏 / 上传截图 | 需自己翻页（兜底） |

- 接口：`POST /api/v1/collect {game_id, method, payload}`
- 新增采集来源 = 在 `app/collectors/` 注册一个插件（只需产出文本行），识别管线完全复用
- 前端：资产识别页「自动导入」模式（选文件 / 粘贴）
