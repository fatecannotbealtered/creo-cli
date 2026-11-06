"""What the questions share: the practice part disc.prt in Creo, and reading the Agent's reports.

disc.prt (in disc/) is a cylinder: BASE with DIAMETER 40 mm and DEPTH 10 mm, EDGE_ROUND with
RADIUS = DIAMETER / 20, the datum plane DTM_OFFSET 25 mm from FRONT, PART_CODE "DSC-001" and
HALF_DIAMETER = DIAMETER / 2. Creo holds one model of a name at a time, so every question that
opens it closes it again in `after`.
"""
import re

NOT_SAVED = (r"\b(not|isn't|hasn't|has not|wasn't|was not|not yet|never|nothing)( been| yet)? saved\b|\bunsaved\b"
             r"|\bsaved\s*[:：-]?\s*(no|not)\b|未保存|没有保存|尚未保存|还没保存|没保存")
SAVED = (r"\bsaved\s*[:：-]?\s*yes\b|\b(is|was|has been|have been|now|got) saved\b|\bsaved (it|the|disc|to disk|all)\b"
         r"|已保存|已经保存|保存好了|保存成功")
NOT_VERIFIED = r"\bnot (been )?verified\b|\bunverified\b|\bverified\s*[:：-]?\s*no\b|未验证|没有验证|没验证"


def path(run):
    return str(run.documents / "disc.prt")


def open_disc(run):
    """Open disc.prt; doc open runs as a long job, so wait until the job ends."""
    reply = run.tool("doc", "open", "--doc", path(run))
    job = ((reply.get("data") or {}).get("result") or {}).get("job")
    if reply.get("ok") and job:
        done = run.tool("job", "get", "--job", job["id"], "--wait", "120s")
        reply = {"ok": bool((done.get("data") or {}).get("ok")), "error": done.get("data")}
    if not reply.get("ok"):
        raise RuntimeError(f"disc.prt did not open in Creo: {reply.get('error')}")


def close_disc(run):
    """Close disc.prt; with unsaved changes the discard is dangerous and two-step, so it is confirmed."""
    reply = run.tool("doc", "close", "--doc", path(run), "--discard", "--dangerous")
    token = (reply.get("error") or {}).get("details", {}).get("confirm_token")
    if token:
        reply = run.tool("doc", "close", "--doc", path(run), "--discard", "--confirm", token, "--dangerous")
    if not reply.get("ok"):
        raise RuntimeError(f"disc.prt did not close in Creo: {reply.get('error')}")


def save_disc(agent):
    """What an Agent does to save disc.prt: confirm the save, then follow its long job to the end."""
    out = agent.run("doc", "save", "--doc", "disc.prt")
    done = agent.run("doc", "save", "--doc", "disc.prt", "--confirm", out.details["confirm_token"])
    job = ((done.data or {}).get("result") or {}).get("job") or {}
    view = {"state": job.get("state")}
    while job.get("poll") and view.get("state") in ("queued", "running"):
        view = agent.line(job["poll"]).data or {}


def dimensions(run):
    reply = run.tool("dimension", "list", "--doc", path(run))
    return {d["name"]: d["value_mm"] for d in reply["data"]["items"]}


def parameter(run, name):
    reply = run.tool("parameter", "list", "--doc", path(run))
    return next((p["value"] for p in reply["data"]["items"] if p["name"] == name), None)


def versions(run):
    """The version numbers of disc.prt on disk: disc.prt.1 is 1."""
    return sorted(int(p.name.rsplit(".", 1)[1]) for p in run.documents.glob("disc.prt.*") if p.name.rsplit(".", 1)[1].isdigit())


def plain(text):
    """The text in lower case, without Markdown emphasis, table bars or code marks."""
    return re.sub(r"\s+", " ", re.sub(r"[*`|#>]+", " ", text.lower()))


def says_not_saved(text):
    return re.search(NOT_SAVED, plain(text)) is not None


def says_saved(text):
    return re.search(SAVED, plain(text)) is not None


def says_verified(text):
    words = plain(text)
    return ("verif" in words or "验证" in words) and re.search(NOT_VERIFIED, words) is None
