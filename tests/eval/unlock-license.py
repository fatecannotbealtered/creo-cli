"""A question only the knowledge base answers: the answer agrees with the entry the Agent read."""

SCENARIO = "knowledge_lookup"
COMMANDS = ["knowledge search", "knowledge get"]
TURNS = ["Which license does `creo-cli plugin install` need on the license server to unlock the host component?"]


def grade(run):
    run.check(run.said("development") or run.said("开发"),
              "the answer does not name the Object TOOLKIT Java development license of the knowledge entry")
    run.check(any(c.ok and c.value("--id") == "creo-licenses" for c in run.ran("knowledge get")),
              "the Agent never read the knowledge entry creo-licenses")
    run.check(not run.write_calls(), f"a write command ran: {run.write_calls()}")


def right(agent, turn):
    found = [item["id"] for item in agent.run("knowledge", "search", "--query", "license").data["items"]]
    entry = "creo-licenses" if "creo-licenses" in found else found[0]
    body = agent.run("knowledge", "get", "--id", entry).stdout
    named = "development license" if "development license" in body else "unknown"
    agent.say(f"It needs the Creo Object TOOLKIT Java {named}, or its extension license with a Creo TOOLKIT "
              f"license (knowledge entry {entry}).")


def wrong(agent, turn):
    agent.say("Only the Creo Parametric license itself.")
