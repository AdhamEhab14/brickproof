"""Where a run's evidence fits in two regulations that ask for robust updates.

This is a map, not a verdict. A regulation is met by a manufacturer's whole process and
judged by an authority or a notified body; a tool run is one piece of evidence for one
part of one clause. Each entry says, in our own words, what the clause asks, what a
BrickProof run does show towards it, and what it does not.

The clause summaries are paraphrases. They were written against the published texts
(see SOURCES, read on the date given), and the official wording is the one that counts.
"""

CHECKED = "2026-10-11"

SOURCES = {
    "UN R156": {
        "title": "UN Regulation No. 156, Software update and software update management system",
        "url": "https://unece.org/sites/default/files/2024-03/R156e%20%282%29.pdf",
    },
    "CRA": {
        "title": "Regulation (EU) 2024/2847, Cyber Resilience Act, Annex I",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=OJ:L_202402847",
    },
}

CLAUSES = [
    {
        "id": "r156-7.2.2.1.1",
        "source": "UN R156",
        "clause": "7.2.2.1.1",
        "asks": "After a failed or interrupted update, the vehicle can go back to the previous "
                "version of its systems, or can be put into a safe state.",
        "shows": "For one controller, every tested interruption by power loss ended with an "
                 "approved image installed and running: the previous one or the new one.",
        "not": "Interruptions other than power loss (a dropped link, a rejected image). Whether "
               "\"an approved image is running\" is a safe state for the vehicle is the "
               "manufacturer's argument to make. Other controllers in the same update.",
        "needs": "recovery",
    },
    {
        "id": "r156-7.2.1.1",
        "source": "UN R156",
        "clause": "7.2.1.1",
        "asks": "The authenticity and integrity of software updates are protected, so that "
                "compromised or invalid updates are reasonably prevented.",
        "shows": "A half-written image is never left installed and running: after each "
                 "interruption the installed bytes are exactly an approved image.",
        "not": "That a forged, altered or unsigned update is refused. BrickProof interrupts a "
               "valid update; it does not attack the update's signature or origin.",
        "needs": "oracle",
    },
    {
        "id": "r156-7.2.2.1.2",
        "source": "UN R156",
        "clause": "7.2.2.1.2",
        "asks": "An update is only started when the vehicle has enough power to finish it, "
                "including a possible recovery.",
        "shows": "Nothing directly. BrickProof covers the case this clause tries to avoid: power "
                 "is lost anyway.",
        "not": "The power check itself.",
        "needs": None,
    },
    {
        "id": "cra-I-2-h",
        "source": "CRA",
        "clause": "Annex I, Part I, (2)(h)",
        "asks": "Essential and basic functions stay available, also after an incident, through "
                "resilience measures.",
        "shows": "A power failure during a firmware update does not leave the device without "
                 "working firmware, at any of the tested points.",
        "not": "Other incidents, and denial-of-service resistance, which the clause also names.",
        "needs": "recovery",
    },
    {
        "id": "cra-I-2-f",
        "source": "CRA",
        "clause": "Annex I, Part I, (2)(f)",
        "asks": "The integrity of stored programs and configuration is protected against "
                "modification the user did not authorise, and corruption is reported.",
        "shows": "An interrupted update does not leave corrupted program code running as if it "
                 "were valid. Where the adapter probes for it, an older image is not accepted "
                 "again afterwards.",
        "not": "Deliberate tampering, and whether the device reports corruption.",
        "needs": "oracle",
    },
    {
        "id": "cra-II-7",
        "source": "CRA",
        "clause": "Annex I, Part II, (7)",
        "asks": "There are mechanisms to distribute updates securely, so that vulnerabilities "
                "are fixed or mitigated in time.",
        "shows": "The last step of that mechanism, installing the update on the device, "
                 "survives power loss.",
        "not": "The distribution itself: servers, transport, signing, timeliness.",
        "needs": "recovery",
    },
]


def _scope(report):
    """In one sentence, how much of the update this run interrupted."""
    cov = report.get("coverage")
    if not cov:
        return "no cuts were planned"
    parts = ["%d of its %d distinct flash states" % (cov["cuts"], cov["distinct_states"])]
    kinds = {("torn" if c["torn"] else "depth" if c["depth"] > 1 else "cut") for c in report["cuts"]
             if not c["baseline"]}
    if "torn" in kinds:
        parts.append("torn erases and programs (modelled)")
    if "depth" in kinds:
        parts.append("a further cut during recovery")
    return "cut at " + ", plus ".join(parts)


def evidence(report):
    """The clauses, each with what THIS run contributes: its status and its scope.

    status   "shown"       the run passed and has what the clause's evidence needs
             "not shown"   the run failed, or lacks the oracle the evidence rests on
             "not tested"  the clause is outside what a run can show
    """
    out = []
    for c in CLAUSES:
        row = dict(c, url=SOURCES[c["source"]]["url"])
        if c["needs"] is None:
            row["status"], row["detail"] = "not tested", ""
        elif not report["passed"]:
            failed = sum(1 for r in report["cuts"] if not r["passed"] and not r["skipped"])
            row["status"], row["detail"] = "not shown", "%d run(s) failed" % failed
        elif c["needs"] == "oracle" and not report["oracle"]:
            row["status"] = "not shown"
            row["detail"] = "the adapter has no oracle, so nothing checked the installed bytes"
        else:
            row["status"], row["detail"] = "shown", _scope(report)
        out.append(row)
    return out
