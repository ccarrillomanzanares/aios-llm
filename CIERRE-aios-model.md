# Cierre de `aios-model` — 26 sep 2026

Proyecto **abandonado** (preentrenamiento desde cero). Se elimina para que no interfiera con `aios-llm`.

## Por qué se abandona
- Preentrenar desde cero era la vía cara y lenta. El objetivo real (asistente de AIOS) se resuelve con fine-tune.
- Bloqueante que nunca se resolvió del todo: los shards existentes están tokenizados con **GPT2** y la receta pedía **Qwen3** (había re-tokenización parcial en `~/corpus/code_train_qwen_*`).
- Ya hubo un intento fallido de destilación a 0.6B.

## Estado en el momento de borrar
- Repo `github.com/ccarrillomanzanares/aios-model` → **TODO publicado**. 0 ficheros sin commitear, 0 commits sin subir.
- Ramas: `main` (41f1c61), `pretrain-fase0` (432cd9b).
- Tamaño: 786 MB (56 MB de .git).

## Lo que NO estaba en git y desaparece con el borrado
- `pretraining/data/` — 556 MB de shards de prueba.
- `pretraining/gen/resultados/**/*.log` — logs de los runs en A100.
- `pretraining/verificacion/` — 65 MB de índices de Debian (SÍ estaba en git).

## Lo que sigue existiendo fuera del repo
- `~/corpus/` — 52 GB de corpus + tokenización Qwen3 parcial. **Pendiente de decisión aparte.**
- Todo el repo, en GitHub.

## Recuperación
`git clone https://github.com/ccarrillomanzanares/aios-model.git`
