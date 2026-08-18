"""训练 fasttext 粗分类器：词条库导出 → 训练 → 保存 models/classifier.bin。

运行（用已装 fasttext 的 toumanfen 环境）：
    D:\\ANA\\envs\\toumanfen\\python.exe scripts/train_classifier.py

训练数据由实体表（角色/武器/圣遗物）+ 材料/其他样本自动生成；
训练完成后项目设 GYZ_USE_FASTTEXT=1 即走真实 fasttext 粗分类。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# fasttext C++ 底层在 Windows 无法写入非 ASCII 路径（项目目录含中文），
# 故模型默认存到用户主目录的 ASCII 路径；可用 GYZ_FASTTEXT_MODEL 覆盖。
MODEL_PATH = Path(os.environ.get(
    "GYZ_FASTTEXT_MODEL", str(Path.home() / ".gyz_models" / "classifier.bin")))
MODEL_DIR = MODEL_PATH.parent

# 词条库之外的补充样本（材料 / 其他）
EXTRA_LINES = {
    "材料": ["摩拉", "精炼矿石", "经验书", "突破材料", "祝圣油膏", "大英雄的经验"],
    "其他": ["随便看看", "这游戏怎么玩"],
}


def build_training_lines() -> list[str]:
    """从词条库生成训练行：__label__<类型> <文本>。"""
    from app import database as db, seed
    seed.seed_all()  # 无数据时灌入种子
    lines: list[str] = []
    for e in db.query("SELECT type, name, aliases FROM entity"):
        label = e["type"]
        lines.append(f"__label__{label} {e['name']}")
        # 别名也作为样本
        for a in json.loads(e["aliases"] or "[]"):
            lines.append(f"__label__{label} {a}")
        # 模拟 OCR 常见后缀，提升对带等级/星级的文本鲁棒性
        if label == "角色":
            lines.append(f"__label__{label} {e['name']} Lv.90")
        elif label == "武器":
            lines.append(f"__label__{label} {e['name']} Lv.90")
            lines.append(f"__label__{label} {e['name']} 五星")
        elif label == "圣遗物":
            for slot in ("花", "羽", "沙", "杯", "头"):
                lines.append(f"__label__{label} {e['name']} {slot}")
    for label, words in EXTRA_LINES.items():
        for w in words:
            lines.append(f"__label__{label} {w}")
    return lines


def main() -> int:
    lines = build_training_lines()
    print(f"训练样本数：{len(lines)}")

    train_file = Path(tempfile.gettempdir()) / "gyz_fasttext_train.txt"
    train_file.write_text("\n".join(lines), encoding="utf-8")

    import fasttext
    print("开始训练（fasttext）...")
    model = fasttext.train_supervised(
        str(train_file), dim=100, epoch=50, minCount=1, wordNgrams=2, lr=0.5)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(str(MODEL_PATH))
    print(f"模型已保存：{MODEL_PATH}")

    # 自检：加载并预测
    loaded = fasttext.load_model(str(MODEL_PATH))
    samples = ["护摩之杖", "胡桃", "炽烈的炎之魔女", "摩拉", "护摩之杖 Lv.90"]
    print("自检预测：")
    for s in samples:
        label, prob = loaded.predict(s)
        print(f"  {s} → {label[0].replace('__label__', '')} (置信度 {prob[0]:.3f})")
    print("训练与自检完成 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
