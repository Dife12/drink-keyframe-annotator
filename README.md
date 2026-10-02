# 喝水视频关键帧标注工具

一个轻量级的 Windows 桌面工具，用于标注已预处理为“每秒一张、每张含 30 帧拼图”的喝水视频关键帧。

## 环境与安装

- Windows 10 / 11
- Python 3.11 或 3.12（推荐 3.12）

在项目根目录执行：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

依赖仅为 `PySide6`。如已创建虚拟环境，也可以直接使用：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 启动

```powershell
.venv\Scripts\python.exe main.py
```

也可在已激活虚拟环境后运行 `python main.py`。

## 使用方法

1. 点击“选择文件夹”，选择包含每秒拼图图片的文件夹。支持 `.jpg`、`.jpeg`、`.png`、`.webp`、`.bmp`，并按自然顺序读取。
2. 图片的排序索引就是保存的 `second`（从 0 开始）；文件名只作显示。
3. 每张图是 5 列 × 6 行的 30 帧拼图。点击格子依次标注：
   - `pick start`：开始拿水杯
   - `drink start`：水杯开始遮住嘴
   - `drink end`：水杯离开嘴、开始能看到嘴
   - `pick end`：把水杯放回
4. 四次点击可跨不同图片完成。第四次完成后，下一次点击自动开始一条新记录。
5. 使用左右方向键或“上一张 / 下一张”切换图片。表格正在编辑时，左右键优先用于编辑文字。`Ctrl+O` 可打开图片文件夹。
6. 右侧表格可双击手动修改四个时间标记；格式为 `second,frame`，例如 `12,17`。`second` 须非负，`frame` 范围为 0–29。允许清空单元格。最后一列 `container type` 使用下拉框选择 `plastic bottle`、`paper cup small` 或 `paper cup large`（新行默认空白）；其修改不会影响四步点击或 Ctrl+Z。
7. `Ctrl+Z` 或“撤销上一次点击”只撤销图片点击，不影响表格手动编辑。刚完成第四步时撤销，会只清空 `pick end` 并回到第四步。
8. 选中表格行后可删除；若删除当前未完成行，下一次图片点击会从 `pick start` 新建一行。
9. 点击“导出 CSV”选择保存位置（也可按 `Ctrl+S`）。若存在未完成行，会先要求确认。CSV 使用 UTF-8 with BOM（`utf-8-sig`），可直接用 Windows Excel 打开。

## CSV 格式

CSV 列固定为：

```text
No.,pick start,drink start,drink end,pick end,container type
1,"0,5","1,8","2,14","3,2",plastic bottle
```

未完成的标记导出为空单元格。

## 坐标准确性

程序把拼图放在 `QGraphicsScene` 的原始图像坐标系 `(0..width, 0..height)` 中。网格边界按 `width * 列 / 5`、`height * 行 / 6` 计算；鼠标点击通过 `mapToScene()` 回到同一坐标系后，用同一公式计算格子。因此图片自适应缩放、窗口改变大小以及图像尺寸不能被 5 或 6 整除时，网格和点击仍保持一致。
