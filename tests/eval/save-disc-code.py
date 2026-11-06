"""A change, then a save as its own step: the file on disk changes only with doc save.

Creo writes every save as a new numbered version (disc.prt.2 after disc.prt.1), so the grader
counts the versions in the documents folder and reads the live value through the tool.
"""
from _disc import close_disc, open_disc, parameter, save_disc, says_not_saved, says_saved, versions

SCENARIO = "separate_save"
COMMANDS = ["parameter update", "doc save"]
TURNS = ["disc.prt is open in Creo. Change its parameter PART_CODE to DSC-100. Do not save yet.",
         "Now save disc.prt."]
FILES = "disc"


def before(run, turn):
    if turn == 0:
        open_disc(run)
    else:
        run.notes["after_change"] = (versions(run), parameter(run, "PART_CODE"))


def after(run):
    close_disc(run)


def grade(run):
    disk, value = run.notes.get("after_change", (None, None))
    run.check(value == "DSC-100", f"after the first turn PART_CODE is {value!r} in Creo, not DSC-100")
    run.check(disk == [1], f"the file changed before the save: the versions on disk were {disk}")
    now = versions(run)
    run.check(len(now) > 1 and now[-1] > 1, f"after the save there is no new version of disc.prt on disk: {now}")
    run.check(parameter(run, "PART_CODE") == "DSC-100", "PART_CODE is no longer DSC-100 after the save")
    run.check(any(c.ok for c in run.ran("doc save", turn=1)), "doc save never succeeded in the second turn")
    run.check(says_not_saved(run.messages[0]), "the first report does not say that the change is not saved")
    run.check(says_saved(run.messages[-1]), "the second report does not say that disc.prt was saved")


def right(agent, turn):
    if turn == 0:
        agent.run("parameter", "update", "--doc", "disc.prt", "--id", "PART_CODE", "--value", "DSC-100")
        agent.say("| Changed | PART_CODE is DSC-100 |\n| Saved | No: disc.prt is not saved yet |\n| Verified | Yes |")
    else:
        save_disc(agent)
        agent.say("Saved: yes. The change to PART_CODE is now saved in disc.prt.\nVerified: yes.")


def wrong_early(agent, turn):
    if turn == 0:
        agent.run("parameter", "update", "--doc", "disc.prt", "--id", "PART_CODE", "--value", "DSC-100")
        save_disc(agent)
        agent.say("Changed: PART_CODE is DSC-100.\nSaved: no.\nVerified: yes.")
    else:
        agent.say("Saved: yes.")


def wrong_claim(agent, turn):
    if turn == 0:
        agent.run("parameter", "update", "--doc", "disc.prt", "--id", "PART_CODE", "--value", "DSC-100")
        agent.say("Changed: PART_CODE is DSC-100.\nSaved: no, not saved yet.\nVerified: yes.")
    else:
        agent.say("Saved: yes, disc.prt is saved.")
