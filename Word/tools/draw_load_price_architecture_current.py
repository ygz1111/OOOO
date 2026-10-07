"""Draw the production load/price architecture; never load TensorFlow or weights.

Evidence: backend/models/tensorflow_load/tf_split_models.py and
current_project_facts.txt.  Shapes omit batch.  At the specified Word width
(16.2 cm), the 72 px minimum font is 10.33 pt.
"""
from pathlib import Path
import math
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / 'Word/materials/thesis_update'
OUTPUT_PATH = OUTPUT_DIR / "load_price_architecture_current.png"
WIDTH, HEIGHT = 3200, 2660
WORD_WIDTH_CM = 16.2
FONT_SIZE = 72
MIN_EFFECTIVE_PT = FONT_SIZE * WORD_WIDTH_CM * 72 / (WIDTH * 2.54)
assert MIN_EFFECTIVE_PT >= 10, MIN_EFFECTIVE_PT

FONTS = Path("C:/Windows/Fonts")
FONT_CN = ImageFont.truetype(str(FONTS / "msyh.ttc"), FONT_SIZE)
FONT_CN_BOLD = ImageFont.truetype(str(FONTS / "msyhbd.ttc"), FONT_SIZE)
FONT_EN = ImageFont.truetype(str(FONTS / "arial.ttf"), FONT_SIZE)
FONT_TITLE = ImageFont.truetype(str(FONTS / "msyhbd.ttc"), 80)
FONT_MODEL = ImageFont.truetype(str(FONTS / "msyhbd.ttc"), 76)

INK = "#23364a"
BORDER = "#617386"
LINE = "#3f5368"
INPUT_FILL = "#e8eff6"
LAYER_FILL = "#f1f3f5"
MERGE_FILL = "#e8efed"
HEAD_FILL = "#f4eee4"
OUTPUT_FILL = "#e6edf4"

image = Image.new("RGB", (WIDTH, HEIGHT), "white")
draw = ImageDraw.Draw(image)
text_boxes = []


def choose_font(text, emphasized=False):
    if any(ord(char) > 127 for char in text):
        return FONT_CN_BOLD if emphasized else FONT_CN
    return FONT_EN


def center_text(text, center_x, top, font, max_width, fill=INK):
    bounds = draw.textbbox((0, 0), text, font=font)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    assert width <= max_width, (text, width, max_width)
    x = center_x - width / 2 - bounds[0]
    y = top - bounds[1]
    draw.text((x, y), text, font=font, fill=fill)
    text_boxes.append((text, (x + bounds[0], top, x + bounds[2], top + height)))
    return height


def node(x, y, width, lines, fill=LAYER_FILL, height=280):
    rect = (x, y, x + width, y + height)
    draw.rounded_rectangle(rect, radius=16, fill=fill, outline=BORDER, width=4)
    fonts = [choose_font(line, emphasized=index == 0) for index, line in enumerate(lines)]
    heights = [draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1]
               for line, font in zip(lines, fonts)]
    gap = 17
    total_height = sum(heights) + gap * (len(lines) - 1)
    assert total_height <= height - 30, (lines, total_height, height)
    top = y + (height - total_height) / 2
    for line, font, line_height in zip(lines, fonts, heights):
        center_text(line, x + width / 2, top, font, width - 40)
        top += line_height + gap
    return rect


def arrow(points):
    draw.line(points, fill=LINE, width=6, joint="curve")
    previous, end = points[-2], points[-1]
    angle = math.atan2(end[1] - previous[1], end[0] - previous[0])
    length, spread = 23, 0.49
    left = (end[0] - length * math.cos(angle - spread), end[1] - length * math.sin(angle - spread))
    right = (end[0] - length * math.cos(angle + spread), end[1] - length * math.sin(angle + spread))
    draw.polygon((end, left, right), fill=LINE)


def connect_row(rectangles):
    for before, after in zip(rectangles, rectangles[1:]):
        arrow([(before[2], (before[1] + before[3]) / 2),
               (after[0], (after[1] + after[3]) / 2)])


def model_card(top, task, past_features):
    card_bottom = top + 1100
    draw.rounded_rectangle((40, top, 3160, card_bottom), radius=22,
                           fill="white", outline="#b3bfca", width=4)
    title = "负荷模型  tf_load_split_v1" if task == "load" else "电价模型  tf_price_split_v1"
    center_text(title, WIDTH / 2, top + 27, FONT_MODEL, 3000)

    positions = [100, 720, 1340, 1960, 2580]
    row1_y, row2_y, row3_y = top + 150, top + 475, top + 805
    historical = [
        node(positions[0], row1_y, 520, ["历史输入", f"168 × {past_features}"], INPUT_FILL),
        node(positions[1], row1_y, 520, ["LayerNorm", f"168 × {past_features}"]),
        node(positions[2], row1_y, 520, ["BiGRU(112)", "168 × 224"]),
        node(positions[3], row1_y, 520, ["GRU(144)", "历史上下文", "144 维"]),
        node(positions[4], row1_y, 520, ["RepeatVector", "重复 24 次", "24 × 144"]),
    ]
    future = [
        node(positions[0], row2_y, 520, ["未来协变量", "24 × 17"], INPUT_FILL),
        node(positions[1], row2_y, 520, ["LayerNorm", "24 × 17"]),
        node(positions[2], row2_y, 520, ["Dense(72)", "swish", "24 × 72"]),
        node(positions[3], row2_y, 520, ["Concatenate", "24 × 216"], MERGE_FILL),
        node(positions[4], row2_y, 520, ["解码器", "GRU(144)", "24 × 144"]),
    ]
    connect_row(historical)
    connect_row(future)
    # The historical context enters Concatenate independently of future features.
    repeat_center = (historical[-1][0] + historical[-1][2]) / 2
    concat_center = (future[-2][0] + future[-2][2]) / 2
    bridge_y = row1_y + 305
    arrow([(repeat_center, historical[-1][3]), (repeat_center, bridge_y),
           (concat_center, bridge_y), (concat_center, future[-2][1])])

    if task == "load":
        output_nodes = [
            node(100, row3_y, 800, ["Dense(96)", "swish", "24 × 96"]),
            node(1200, row3_y, 800, ["逐时 Dense(1)", "TimeDistributed", "24 × 1"], HEAD_FILL),
            node(2300, row3_y, 800, ["模型输出", "24 × 1", "RT_Demand"], OUTPUT_FILL),
        ]
    else:
        output_nodes = [
            node(100, row3_y, 620, ["Dense(96)", "swish", "24 × 96"]),
            node(890, row3_y, 620, ["逐时 Dense(3)", "TimeDistributed", "24 × 3"], HEAD_FILL),
            node(1680, row3_y, 620, ["OrderedQuantiles", "24 × 3"], HEAD_FILL),
            node(2470, row3_y, 620, ["模型输出", "24 × 3", "P10 / P50 / P90"], OUTPUT_FILL),
        ]
    connect_row(output_nodes)
    # Wrap the decoder path in the gap between rows, without crossing any node.
    decoder_center = (future[-1][0] + future[-1][2]) / 2
    dense_center = (output_nodes[0][0] + output_nodes[0][2]) / 2
    decoder_bridge_y = row2_y + 305
    arrow([(decoder_center, future[-1][3]), (decoder_center, decoder_bridge_y),
           (dense_center, decoder_bridge_y), (dense_center, output_nodes[0][1])])


center_text("同构网络分别实例化、独立训练；负荷与电价不共享权重", WIDTH / 2, 39,
            FONT_TITLE, 3060)
model_card(170, "load", 21)
model_card(1320, "price", 26)
center_text("形状省略 batch 维；各自保存权重、缩放器与元数据。", WIDTH / 2, 2457,
            FONT_CN, 3060)
center_text("输出经各自逆变换还原：负荷为 MW，电价为 USD/MWh。", WIDTH / 2, 2555,
            FONT_CN, 3060)

for text, bounds in text_boxes:
    assert 0 <= bounds[0] < bounds[2] <= WIDTH, (text, bounds)
    assert 0 <= bounds[1] < bounds[3] <= HEIGHT, (text, bounds)

image.save(OUTPUT_PATH, dpi=(500, 500))
print(f"Saved: {OUTPUT_PATH}")
print(f"Pixels: {WIDTH} x {HEIGHT}")
print(f"Word width: {WORD_WIDTH_CM:.1f} cm; height: {HEIGHT / WIDTH * WORD_WIDTH_CM:.2f} cm")
print(f"Minimum effective font: {MIN_EFFECTIVE_PT:.2f} pt")
print(f"Checked text bounds: {len(text_boxes)}")
