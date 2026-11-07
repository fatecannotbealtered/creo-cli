"""Build the rocker switch's cap from the requirement text, in an empty part, and save it.

The grader reads the part in Creo through the tool: its size with the pins, the R30 roof, the shell by
the volume (open at the bottom 609 mm³, closed about 785), and the two pins on one axis across the width,
at the middle of the length and 2 mm above the bottom.
"""
from _ps4 import build_key, check_saved, close_part, close_to, cylinders, errors, extents, open_part, parameters, same_sizes, summary, surfaces

SCENARIO = "scoped_change"
COMMANDS = ["parameter update", "model update", "extrude create", "shell create", "pattern create", "model check", "doc save"]
TURNS = ["{documents}/ps4_key.prt 是用公制模板新建的空零件，已在 Creo 里打开。按下面的要求把排插的开关按钮建出来，做完存盘。\n\n"
         "开关按钮（船形开关的翘板帽）\n"
         "- 长18.6 mm、宽12.6 mm，比开关开口每边小0.2 mm。顶面是R30的圆弧，最高处8 mm。\n"
         "- 里面抽壳，壁厚1 mm。两侧各一个转轴销，直径2 mm，伸出1.5 mm，两个销同轴，位于长度中点、离底面2 mm。\n"
         "- 材料用Creo材料库里的PC；PART_NO填PS4-KEY，DESCRIPTION填“开关按钮”。"]
FILES = "key-start"
# Only on the real Creo: the grader reads the geometry Creo built.
FAKE_HOST = None
DOC = "ps4_key.prt"


def before(run, turn):
    open_part(run, DOC)


def after(run):
    close_part(run, DOC)


def grade(run):
    model = summary(run, DOC)
    size = extents(model)
    run.check(same_sizes(model, [18.6, 15.6, 8]), f"the cap with its pins measures {size} mm, not 18.6 x 15.6 x 8")
    volume = model.get("volume_mm3") or 0
    run.check(595 <= volume <= 800, f"the volume is {volume} mm³; a 1 mm shell gives 609 open, about 785 closed")
    run.check(str(model.get("material") or "").upper() == "PC", f"the material is {model.get('material')}, not PC")
    params = parameters(run, DOC)
    run.check(params.get("PART_NO") == "PS4-KEY", f"PART_NO is {params.get('PART_NO')!r}")
    run.check(params.get("DESCRIPTION") == "开关按钮", f"DESCRIPTION is {params.get('DESCRIPTION')!r}")
    faces = surfaces(run, DOC)
    roof = cylinders(faces, 30)
    run.check(roof, "no R30 roof")
    pins = cylinders(faces, 1)
    run.check(len(pins) >= 2, "no pins of 2 mm")
    if roof and pins and same_sizes(model, [8, 15.6, 18.6]):
        box = model["bounding_box_mm"]
        across = next(i for i in range(3) if close_to(size[i], 15.6))
        up = next(i for i in range(3) if close_to(size[i], 8))
        along = 3 - across - up
        run.check(all(abs(abs(p["axis_direction"][across]) - 1) < 1e-6 for p in pins), "the pins do not point across the width")
        run.check(len({(round(p["axis_origin_mm"][up], 3), round(p["axis_origin_mm"][along], 3)) for p in pins}) == 1,
                  "the two pins are not on one axis")
        # The roof's axis lies 22 mm below the bottom, so the bottom is the side of the box nearer to it.
        low = box["min"][up] if roof[0]["axis_origin_mm"][up] < (box["min"][up] + box["max"][up]) / 2 else box["max"][up]
        run.check(close_to(abs(pins[0]["axis_origin_mm"][up] - low), 2), "the pins are not 2 mm above the bottom")
        run.check(close_to(pins[0]["axis_origin_mm"][along], (box["min"][along] + box["max"][along]) / 2),
                  "the pins are not at the middle of the length")
    run.check(errors(run, DOC) == 0, "model check reports errors")
    check_saved(run, DOC)


def right(agent, turn):
    build_key(agent)
    agent.say("开关按钮建好了。\n- **改动：** ps4_key.prt 建出 R30 圆弧顶的帽体，抽壳 1 mm，两侧各一个 2 mm 转轴销，同轴。\n"
              "- **存盘：** 已保存。\n- **核对：** 每步都读回核对过，model check 没有错误。")


def wrong(agent, turn):
    build_key(agent, shell=False)
    agent.say("开关按钮建好了，已保存，model check 没有错误。")
