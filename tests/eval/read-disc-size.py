"""Answer a question about the practice part by reading it in Creo, and change nothing."""
from _disc import close_disc, open_disc

SCENARIO = "read_answer"
COMMANDS = ["dimension list"]
TURNS = ["disc.prt is open in Creo. What are its diameter and its depth?"]
FILES = "disc"
# Only on the real Creo: the sizes come from what Creo reads in disc.prt.
FAKE_HOST = None


def before(run, turn):
    open_disc(run)


def after(run):
    close_disc(run)


def grade(run):
    run.check(run.said("40") and run.said("10"), "the answer does not give the diameter, 40 mm, and the depth, 10 mm")
    run.check(not run.write_calls(), f"a write command ran: {run.write_calls()}")


def right(agent, turn):
    items = agent.run("dimension", "list", "--doc", "disc.prt").data["items"]
    size = {d["name"]: d["value_mm"] for d in items}
    agent.say(f"disc.prt has a diameter of {size['DIAMETER']:g} mm and a depth of {size['DEPTH']:g} mm.")


def wrong_guess(agent, turn):
    agent.say("disc.prt is 50 mm across and 5 mm deep.")


def wrong_write(agent, turn):
    # Writes the depth it read back, "to make sure".
    agent.run("dimension", "update", "--doc", "disc.prt", "--id", "DEPTH", "--length", "10mm")
    agent.say("disc.prt has a diameter of 40 mm and a depth of 10 mm.")
