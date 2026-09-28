#!/usr/bin/env python3
"""Checks the model's CLOSING ANSWER against what the case says is true.

Why this exists at all, and it is the most important correction of the whole
28-sep review: the bench only ever checked WHICH TOOL the model called and with
what arguments. It never compared the answer to reality. So this happened:

    "How many packages are installed?"   (the machine has 428)
      4B  answered "0 packages installed"   (false)  -> PASSED
      35B answered "432" with sven's real data       -> FAILED

The bench was rewarding the exact vice the project's plan calls the hardest to
teach and the most valuable: never assert what a tool has not returned. A check
that cannot tell 0 from 428 is not checking anything.

The field is optional and case-declared, so nothing changes for cases that do not
use it:

    "respuesta_contiene_alguno": ["428", "432", "433"]

It lives in its own module so that `bateria_agente.py` (which produced the
project's baseline) is not touched even to add a check.

Returns True / False / None (None = the case does not declare it, i.e. not
applicable, which is different from failing).
"""
import re


def texto_final(mensajes):
    """The closing answer of a trajectory, untruncated.

    Read from the trajectory and not from the result row on purpose: the row
    stores `texto_final` cut to 300 characters, and the number a case is looking
    for can easily fall past the cut.
    """
    for m in reversed(mensajes or []):
        if m.get("role") == "assistant" and (m.get("content") or "").strip():
            return m["content"]
    return ""


def revisar(caso, texto):
    """True if any of the expected strings appears in the closing answer."""
    esperados = caso.get("respuesta_contiene_alguno")
    if not esperados:
        return None
    t = (texto or "").lower()
    return any(str(e).lower() in t for e in esperados)


def detalle(caso, texto):
    esperados = caso.get("respuesta_contiene_alguno") or []
    if not esperados:
        return ""
    return "expected any of %s in the answer, got: %s" % (esperados, (texto or "")[:160])


# --- a light self-test, because a checker nobody checks is how this project got
# --- 25 instrument faults in the first place
if __name__ == "__main__":
    caso = {"respuesta_contiene_alguno": ["428", "432", "433"]}
    casos = [
        ("Tienes **428 paquetes instalados**", True),
        ("Sono installati 432 pacchetti", True),
        ("Aktuell sind **0 Pakete** installiert", False),
        ("There are no packages installed", False),
    ]
    fallos = 0
    for texto, esperado in casos:
        got = revisar(caso, texto)
        marca = "ok " if got == esperado else "MAL"
        if got != esperado:
            fallos += 1
        print("  %s %-45r -> %s (esperado %s)" % (marca, texto[:43], got, esperado))
    print("  not applicable (case without the field):", revisar({}, "lo que sea"))
    print("SELF-TEST:", "OK" if fallos == 0 else "%d FALLOS" % fallos)
    raise SystemExit(1 if fallos else 0)
