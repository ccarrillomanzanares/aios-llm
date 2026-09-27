#!/bin/bash
# The two measurements agreed with Carlos, one after the other, with production
# restored at the end so nobody has to remember to do it.
#
#   A) short prompt   -> how much of the 93% is the model and how much the scaffolding
#   B) thinking off   -> whether the internal monologue is what makes it explain instead of act
#
# Both run against the 4B in its isolated container. Same bench, same oracle.
cd /home/ccmai/aios-llm/bateria || exit 1

echo "=== A: short prompt $(date -Is) ==="
sudo python3 -u bateria_agente.py --url http://127.0.0.1:8099 --modelo qwen3.5-4b \
     --etiqueta 4b-prompt-corto --prompt prompt_corto.txt > medida-A.log 2>&1

echo "=== B: thinking off $(date -Is) ==="
sudo python3 -u bateria_agente.py --url http://127.0.0.1:8099 --modelo qwen3.5-4b \
     --etiqueta 4b-sin-thinking --sin-thinking > medida-B.log 2>&1

echo "=== restoring production $(date -Is) ==="
sudo docker start llama-qwen > /dev/null 2>&1
echo "llama-qwen restarted at $(date -Is)" > rearranque-medidas.log
echo "=== done $(date -Is) ==="
