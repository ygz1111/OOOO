# 论文制作支持工具

本目录保存论文制作过程中的支持工具，供明确需要重新生成或核验时手动使用。项目启动、模型训练及页面运行不会自动执行这些脚本。本轮整理只修正工具路径和检查方式，未修改论文正文、DOCX、原图、源表或验收记录。

脚本根据自身位置确定项目根目录，不依赖运行时所在目录：论文位于 `Word/`，制作素材、源表和记录位于 `Word/materials/thesis_update/`，保留的最终页面图片位于该目录下的 `delivery_checked/`。两张前端改版验收截图使用 `docs/evidence/frontend/` 中的原文件；原论文截图另存于 `Word/assets/screenshots/`。

| 工具 | 用途及运行影响 |
| --- | --- |
| `update_thesis.py` | 从“初始化.docx”生成“项目更新排版版.docx”，覆盖同名输出和 `edit_manifest.json`。它不是对当前排版版的增量编辑，直接重跑会覆盖后续人工修改。 |
| `finish_layout.py` | 手动修正生成稿中两处 API 方法单元格换行，保存排版版并写入布局记录。它只适用于尚未完成该处理的生成稿，不能重复用于已交付稿。 |
| `draw_scientific_charts.py` | 按既有 `source_tables.json` 数值绘制负荷、光伏对比图，将同名 PDF/PNG 输出到素材目录。它不重新评价或训练模型。 |
| `draw_load_price_architecture_current.py` | 绘制负荷、电价架构图，覆盖素材目录中的同名 PNG。 |
| `render_review.py` | 通过本机 Microsoft Word 更新目录、字段和分页，保存排版版并导出 PDF、页面图片及文本。运行时会修改 DOCX；应使用新的渲染目录名，不覆盖保留的 `delivery_checked`。 |
| `verify_delivery.py` | 只读检查原稿 SHA、封面字段、输出 DOCX 基本结构、输出 SHA 与原验收记录是否一致，以及保留页面文件是否齐全，仅向终端输出结果，不写入验收记录。 |

生成、排版、绘图和渲染前，应先另存当前成果，再明确执行相应工具。部分脚本在直接运行或导入时即开始写文件，不要通过导入这些脚本进行检查。绘图与文档工具需要各自现有依赖；渲染还依赖本机 Word、Windows 字体和脚本指定的文档渲染器路径。

只读交付检查可在已安装 `python-docx` 的 Python 环境手动执行：

```powershell
python Word/tools/verify_delivery.py
```

该检查保留 52 页快照的来源与完整性口径：页数来自留存图片和既有验收记录，不代表重新分页；SHA 一致也不代表本轮重新完成视觉验收。旧 `final_checked` 图片已归入可恢复备份，工具不再比较它与 `delivery_checked` 的像素，也不生成“页面像素相同”或“逐页已检查”的结论。素材目录内旧记录中的绝对路径保留为历史制作信息，不用于当前工具定位。

本轮验证完成六个 Python 文件的 AST 语法编译、14 项必要路径检查，并执行了只读 `verify_delivery.py`，五项检查全部通过。没有执行写入、绘图或渲染工具，没有重画图片或重新生成论文。
