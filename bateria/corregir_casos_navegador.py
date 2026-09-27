#!/usr/bin/env python3
"""Fixes the three browser cases that assumed a page was already open.

What the trajectories showed, read rather than guessed: `nave-listar`,
`nave-pulsar` and `nave-escribir` said "on the page you have open" without ever
opening one. The bench starts chromium fresh at `about:blank` for each case, so
there was nothing to interact with — and the model did the RIGHT thing:

    "No hay elementos interactivos en la página actual — probablemente no haya
     ninguna página cargada. ¿A qué página debo navegar primero?"

It asked instead of inventing a click. That is the behaviour the whole project is
trying to produce, and the case was marking it down. Fourth time.

Two faults, both the instrument's:

  1. The cases need to establish the scene. A real user has a page open, so the
     bench must say to open it — which also makes them genuinely multi-step, the
     thing this bench exists to measure.
  2. `nave-listar`'s comprobacion required only `"elements"` in the answer, and
     `{"count": 0, "elements": []}` contains that string. A check that passes on
     an empty result is a check that lies. It now requires the real button.
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
RUTA = os.path.join(BASE, "casos.json")

URL = "http://127.0.0.1:8099/fixture.html"

TEXTO = {
    "nave-listar": {
        "en": "Open " + URL + " and list the elements I can interact with.",
        "es": "Abre " + URL + " y lista los elementos con los que puedo interactuar.",
        "fr": "Ouvre " + URL + " et liste les éléments avec lesquels je peux interagir.",
        "de": "Öffne " + URL + " und liste die Elemente auf, mit denen ich interagieren kann.",
        "it": "Apri " + URL + " ed elenca gli elementi con cui posso interagire.",
        "pt": "Abre " + URL + " e lista os elementos com que posso interagir.",
    },
    "nave-pulsar": {
        "en": "Open " + URL + " and click the 'Enviar' button.",
        "es": "Abre " + URL + " y pulsa el botón 'Enviar'.",
        "fr": "Ouvre " + URL + " et clique sur le bouton « Enviar ».",
        "de": "Öffne " + URL + " und klicke auf die Schaltfläche 'Enviar'.",
        "it": "Apri " + URL + " e clicca sul pulsante 'Enviar'.",
        "pt": "Abre " + URL + " e clica no botão 'Enviar'.",
    },
    "nave-escribir": {
        "en": "Open " + URL + " and type the text AIOS-2026 into its search field.",
        "es": "Abre " + URL + " y escribe el texto AIOS-2026 en su campo de búsqueda.",
        "fr": "Ouvre " + URL + " et tape le texte AIOS-2026 dans son champ de recherche.",
        "de": "Öffne " + URL + " und schreibe den Text AIOS-2026 in das Suchfeld.",
        "it": "Apri " + URL + " e scrivi il testo AIOS-2026 nel suo campo di ricerca.",
        "pt": "Abre " + URL + " e escreve o texto AIOS-2026 no seu campo de pesquisa.",
    },
}

# The comprobacion of nave-listar passed on an EMPTY element list. The fixture's
# button is what makes it meaningful, and it is stable.
COMPROBACION_LISTAR = {"herramienta": "browser_elements", "args": {"limit": 10},
                       "contiene": "Enviar"}

POR_QUE = {
    "nave-listar": ("Enumerating what can be interacted with BEFORE interacting. This is the tool that "
                    "separates an agent that acts from one that guesses selectors. The case opens the "
                    "fixture itself, because the bench starts chromium at about:blank and a real user "
                    "has a page open. Its check demands the fixture's real button: an earlier version "
                    "required only the string 'elements', which `{\"count\": 0, \"elements\": []}` also "
                    "contains — a check that passes on an empty answer is a check that lies."),
    "nave-pulsar": ("Clicking by SELECTOR. The alternative (screen coordinates) is what this tool exists "
                    "to avoid. Measured: with no page open the model correctly refused to click and "
                    "asked which page to open; the case was punishing that, so it now opens the fixture "
                    "first."),
    "nave-escribir": ("Typing into a FORM FIELD. The fixture has exactly one input, so the selector cannot "
                      "be ambiguous, and the model must not fall back to xdotool, which types into "
                      "whatever window happens to be focused. The page is opened by the case itself, "
                      "which also makes this genuinely multi-step."),
}


def main():
    banco = json.load(open(RUTA, encoding="utf-8"))
    tocados = []
    for c in banco["casos"]:
        if c["id"] not in TEXTO:
            continue
        if c["idiomas"] == TEXTO[c["id"]]:
            continue
        c["idiomas"] = TEXTO[c["id"]]
        c["por_que"] = POR_QUE[c["id"]]
        if c["id"] == "nave-listar":
            c["comprobacion"] = COMPROBACION_LISTAR
        tocados.append(c["id"])
    if not tocados:
        print("nothing to fix (already applied)")
        return 0
    json.dump(banco, open(RUTA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("fixed: %s" % ", ".join(tocados))
    print("they now open the fixture themselves, so they are multi-step and truthful")
    return 0


if __name__ == "__main__":
    sys.exit(main())
