"""Build the power strip's top housing from the requirement text, in an empty part, and save it.

The grader reads the part in Creo through the tool. Draft before or after the shell, the depth of the
screw holes (the text gives none) and how far the ribs reach move the volume between about 44,900 and
48,100 mm³ (creo-cli's own build: 47,881); the faces show the ribs, bosses and holes.
"""
from _ps4 import (build_top, check_saved, close_part, cylinders, dimensions, errors, extents, named, open_part, parameters,
                  same_sizes, summary, surfaces)

SCENARIO = "scoped_change"
COMMANDS = ["parameter update", "model update", "extrude create", "draft create", "round create", "shell create",
            "pattern create", "plane create", "parameter create", "relation update", "model check", "doc save"]
TURNS = ["{documents}/ps4_top.prt 是用公制模板新建的空零件，已在 Creo 里打开。按下面的要求把四位独立开关排插的上壳建出来，"
         "做完存盘。\n\n"
         "上壳\n"
         "- 外形是长280 mm、宽55 mm、高22 mm的盒子，四条竖边圆角R8，顶面外边缘圆角R2。底面敞开，壁厚2 mm。外侧壁拔模1°，开模方向朝上。\n"
         "- 顶面沿长度方向排四个位置，间距62 mm，整排居中。每个位置有一个插座开口（36×36 mm，四角R3，装插座模块）和它旁边的一个"
         "开关开口（13×19 mm，19 mm沿宽度方向，装船形开关）。\n"
         "- 长度由位置的个数和间距决定，两端各留16 mm。\n"
         "- 相邻两个位置之间有一道横向隔筋，厚1.2 mm，从顶面内侧往下15 mm。\n"
         "- 四角各一个螺丝柱，外径6 mm，孔径2.5 mm，柱子从顶面内侧做到离底边2 mm处，中心离外边缘8 mm。\n"
         "- 材料用Creo材料库里的ABS；零件参数PART_NO填PS4-TOP，DESCRIPTION填“四位排插上壳”。\n"
         "- 位置个数、间距、壁厚、长度、宽度、高度都是有名字的尺寸或参数。"]
FILES = "top-start"
# Only on the real Creo: the grader reads the geometry Creo built.
FAKE_HOST = None
DOC = "ps4_top.prt"


def before(run, turn):
    open_part(run, DOC)


def after(run):
    close_part(run, DOC)


def grade(run):
    model = summary(run, DOC)
    run.check(same_sizes(model, [280, 55, 22]), f"the housing measures {extents(model)} mm, not 280 x 55 x 22")
    volume = model.get("volume_mm3") or 0
    run.check(44900 <= volume <= 48100, f"the volume is {volume} mm³, outside 44,900 to 48,100")
    run.check(str(model.get("material") or "").upper() == "ABS", f"the material is {model.get('material')}, not ABS")
    params = parameters(run, DOC)
    run.check(params.get("PART_NO") == "PS4-TOP", f"PART_NO is {params.get('PART_NO')!r}")
    run.check(params.get("DESCRIPTION") == "四位排插上壳", f"DESCRIPTION is {params.get('DESCRIPTION')!r}")
    dims = dimensions(run, DOC)
    for value, what in ((4, "position count"), (62, "pitch"), (2, "wall"), (280, "length"), (55, "width"), (22, "height")):
        run.check(named(params, dims, value), f"no parameter or named dimension holds the {what}, {value}")
    length = [d for d in dims if d.get("value_mm") == 280]
    run.check(any(d.get("driven_by_relation") for d in length), "no relation drives the 280 mm length")
    faces = surfaces(run, DOC)
    run.check(len(cylinders(faces, 1.25)) >= 4, "fewer than four 2.5 mm screw holes")
    run.check(len(cylinders(faces, 3)) >= 20, "fewer cylinders of R3 than 16 socket corners and four 6 mm bosses make")
    along = extents(model).index(max(extents(model)))
    walls = [f for f in faces if f.get("shape") == "plane" and f.get("normal") and abs(f["normal"][along]) > 0.9999]
    run.check(len(walls) >= 22, f"{len(walls)} faces cross the length; four sockets, four switches and three ribs make 22")
    run.check(errors(run, DOC) == 0, "model check reports errors")
    check_saved(run, DOC)


def right(agent, turn):
    build_top(agent)
    agent.say("上壳建好了。\n- **改动：** ps4_top.prt 按要求建出外壳、四个插座和开关开口、三道隔筋和四个螺丝柱；"
              "POSITIONS 和 PITCH 通过关系驱动长度和各排。\n- **存盘：** 已保存。\n- **核对：** 每步都读回核对过，model check 没有错误。")


def wrong(agent, turn):
    build_top(agent, relations=False)
    agent.say("上壳建好了，已保存，model check 没有错误。")
