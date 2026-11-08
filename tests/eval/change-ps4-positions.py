"""Apply the change order to the housing: five positions, 58 mm apart, 2.5 mm walls; then save.

top-built/ps4_top.prt is the housing as creo-cli builds it from the requirement text, with POSITIONS and
PITCH driving it through relations. The grader reads the part in Creo through the tool; creo-cli's own
change gives a 322 mm housing of 64,643 mm³.
"""
from _ps4 import check_saved, close_part, dimensions, errors, extents, open_part, parameters, same_sizes, save, summary

SCENARIO = "scoped_change"
COMMANDS = ["parameter update", "dimension update", "model check", "doc save"]
TURNS = ["{documents}/ps4_top.prt 是四位排插的上壳，已在 Creo 里打开。设变：改成五个位置、间距58 mm、壁厚2.5 mm。"
         "改完之后长度自动变成322 mm，五个插座开口和五个开关开口各在自己的位置上，模型正常重新生成，model check没有错误。"
         "改完存盘。"]
FILES = "top-built"
# Only on the real Creo: the change runs through the relations Creo keeps in the part.
FAKE_HOST = None
DOC = "ps4_top.prt"


def before(run, turn):
    open_part(run, DOC)


def after(run):
    close_part(run, DOC)


def grade(run):
    model = summary(run, DOC)
    run.check(same_sizes(model, [322, 55, 22]), f"the housing measures {extents(model)} mm, not 322 x 55 x 22")
    volume = model.get("volume_mm3") or 0
    run.check(abs(volume - 64643.29) <= 5, f"the volume is {volume} mm³, not 64,643 as five positions with 2.5 mm walls make")
    params = parameters(run, DOC)
    run.check(params.get("POSITIONS") == 5 and params.get("PITCH") == 58,
              f"POSITIONS is {params.get('POSITIONS')} and PITCH {params.get('PITCH')}, not 5 and 58")
    wall = [d.get("value_mm") for d in dimensions(run, DOC) if d.get("id") == "WALL"]
    run.check(wall == [2.5], f"WALL is {wall}, not 2.5 mm")
    run.check(errors(run, DOC) == 0, "model check reports errors")
    check_saved(run, DOC)


def right(agent, turn):
    doc = ["--doc", DOC]
    agent.run("parameter", "update", *doc, "--id", "POSITIONS", "--value", "5")
    agent.run("parameter", "update", *doc, "--id", "PITCH", "--value", "58")
    agent.run("dimension", "update", *doc, "--id", "WALL", "--length", "2.5mm")
    agent.run("model", "check", *doc)
    save(agent, DOC)
    agent.say("设变做完了。\n- **改动：** POSITIONS 改为 5，PITCH 改为 58，WALL 改为 2.5 mm；长度随关系变成 322 mm，五个插座和开关开口各就各位。\n"
              "- **存盘：** 已保存。\n- **核对：** 读回核对过，model check 没有错误。")


def wrong(agent, turn):
    agent.run("parameter", "update", "--doc", DOC, "--id", "POSITIONS", "--value", "5")
    save(agent, DOC)
    agent.say("改成五个位置了，已保存。")
