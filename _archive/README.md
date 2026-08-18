# _archive · 归档区

已被新功能取代或不再使用的文件，仅留档备查（不参与运行）。

| 文件 | 原位置 | 弃用原因 | 替代 |
|---|---|---|---|
| `scripts/gen_random_data.py` | scripts/ | 旧的随机账户数据生成器 | `scripts/gen_test_data.py`（实时生成 66 角色/150 武器/1000 圣遗物/400 材料） |
| `tools/sample_ocr.txt` | tools/ | 旧版 OCR 离线样例（格式过时） | `tools/sample_detail.txt`、`tools/sample_ocr_20.txt`（stress 测试在用） |
| `tools/_api_smoke_report.txt` | tools/ | `scripts/api_smoke.py` 的临时输出报告 | 每次运行 `python scripts/api_smoke.py` 重新生成 |

> 恢复方法：把文件移回原目录即可（路径见"原位置"列）。
