#!/bin/bash
# Re-runs ONLY the cases whose TEXT changed, because a re-score cannot fix those:
# the saved trajectories answered a question that no longer exists.
#
# `ident-guardar` used to claim the machine uses a static IP, which is false. Its
# wording is now true (sven is the package manager), so measuring the old
# trajectories against the new text would score an answer to a question nobody
# asked. 12 evaluations in total: 6 languages x 2 models.
set -u
cd /home/ccmai/aios-llm/bateria || exit 1

echo "=== 35B (professor) $(date -Is) ==="
sudo python3 -u bateria_agente_v2.py --solo ident-guardar \
  --url http://172.19.0.2:8080 --modelo "/models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf" \
  --etiqueta 35b-ident-nuevo > reident-35b.log 2>&1

echo "=== 4B (student) $(date -Is) ==="
sudo python3 -u bateria_agente_v2.py --solo ident-guardar \
  --url http://127.0.0.1:8099 --modelo qwen3.5-4b \
  --etiqueta 4b-ident-nuevo > reident-4b.log 2>&1

echo "=== done $(date -Is) ==="
