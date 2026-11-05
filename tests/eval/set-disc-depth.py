"""Make an explicit change inside the scope, then report changed, saved and verified.

The grader reads the dimensions in Creo through the tool and the recorded runs.
"""
from _disc import close_disc, dimensions, open_disc, says_not_saved, says_verified

SCENARIO = "scoped_change"
COMMANDS = ["dimension update"]
TURNS = ["disc.prt is open in Creo. Set its depth to 12 mm."]
FILES = "disc"


def before(run, turn):
    open_disc(run)


def after(run):
    close_disc(run)


def grade(run):
    size = dimensions(run)
    run.check(size.get("DEPTH") == 12.0, f"DEPTH is {size.get('DEPTH')} mm in Creo, not 12 mm")
    run.check(size.get("DIAMETER") == 40.0, f"DIAMETER changed too: {size.get('DIAMETER')} mm")
    writes = [c for c in run.write_calls() if c.ok]
    run.check(len(writes) == 1, f"{len(writes)} writes succeeded, not one: {writes}")
    message = run.messages[-1]
    run.check(says_not_saved(message), "the report does not say that the change is not saved yet")
    verified = writes and (writes[-1].data or {}).get("receipt", {}).get("outcome", {}).get("verification") == "passed"
    run.check(not verified or says_verified(message), "read-back verified the change, but the report does not say so")


def right(agent, turn):
    out = agent.run("dimension", "update", "--doc", "disc.prt", "--id", "DEPTH", "--length", "12mm")
    outcome = out.data["receipt"]["outcome"]
    agent.say(f"- **Changed:** DEPTH of disc.prt is now 12 mm.\n- **Saved:** No, disc.prt is not saved yet.\n"
              f"- **Verified:** {'Yes, read back from Creo' if outcome['verification'] == 'passed' else 'No'}.")


def wrong_report(agent, turn):
    agent.run("dimension", "update", "--doc", "disc.prt", "--id", "DEPTH", "--length", "12mm")
    agent.say("Done, the depth is 12 mm.")


def wrong_dimension(agent, turn):
    agent.run("dimension", "update", "--doc", "disc.prt", "--id", "DIAMETER", "--length", "12mm")
    agent.say("Changed: disc.prt is now 12 mm.\nSaved: no, not saved yet.\nVerified: yes.")
