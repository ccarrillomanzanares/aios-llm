# aios-llm

A small LLM that **fits on CPU** and is the assistant of **AIOS**, not of Linux in general.

AIOS is **Linux From Scratch + `sven`**: `apt`, `dnf` and `pacman` **do not exist** there, and no
public model has ever seen that. Any model answers the most frequent task of a system assistant
wrongly — installing and managing software — and that is not fixed with more parameters.

## The problem it solves

Today, before every answer, the model has to be given a system prompt of **11.881 characters**
plus 29 tool schemas. On CPU that costs **~96 s for the first turn of a session** and ~6 s for the
following ones, which is the prefix cache of `llama-server` doing its job with an identical prefix
that repeats on every request.

The goal is not to “know more”: it is to **internalize the contract in the weights** so it can serve
with a prompt of ~800 tokens. That is why TTFT and prompt tokens are measured before and after.

## Measured state

| | Multi-step | Single-step |
|---|---|---|
| Evaluation bench (29 cases × 6 languages) | **173/174 = 99,4 %** | 154/174 = 88,5 % |
| Security traps | **53/54 = 98 %** | 50/54 = 93 % |
| Tasks verified by real execution | **12/12** | — |

Measured model: **Qwen3.6-35B-A3B** (the one serving in production today). That number is the **bar**
the small model has to clear in the AIOS domain to be integrated. If it does not clear it, the
result still counts: the 35B stays, and here is the number that proves it.

**Multi-step is not an implementation detail**: with the same model, measuring in a single step gives
**11 points less**. A bench of one request → one response scores an agent that works in several steps
badly, and the error is not visible: it looks like the model is failing.

## How it is put together

| | |
|---|---|
| `bateria/` | The evaluation bench: cases, executor, harnesses and the **real production contract** |
| `bateria/ejecutor.py` | Translates the 29 `aios-agent` tools into real commands against the oracle |
| `bateria/repuntuar.py` | Re-scores an already completed run when the failure was in the instrument |
| `oracle/oracle.sh` | The oracle: a disposable copy of AIOS (chroot + overlay) |
| `auditoria/` | Audit of the permission layer of `aios-agent` and its non-regression bench |
| `ESTADO.md` | **The living document of the project**: what is done, what was measured and what is missing |

### The oracle

A `chroot` over the rootfs extracted from the squashfs of the published ISO, with the base tree
**read-only** and a disposable write layer on top. It is the same version the users have, and the
measured throughput is **0,17 s per write + reset cycle**.

```bash
sudo oracle/oracle.sh setup            # mounts (idempotent)
sudo oracle/oracle.sh run -- "CMD"     # runs WITHOUT resetting
sudo oracle/oracle.sh reset            # discards the disposable layer
sudo oracle/oracle.sh verify           # integrity: 8 checks
```

Nothing runs without `verify` before and after: **a bench that is not checked fabricates fake
data in silence**, which in a project of “dataset verified by execution” is the worst possible
result.

## Two rules of the project

> **“The good file exists” ≠ “the file that runs is the good one”.**

The md5 is verified **on the machine that RUNS**, not only on the origin machine, and an md5 that
does not match is not ignored: it is stopped and fixed.

> **A case that fails is a HYPOTHESIS, not a verdict.**

Before blaming a failure on the model, **read the real call**. In the first full run,
**6 of the 7 failures were in the instrument**: a forbidden-string pattern that caught too much, and
valid ways of solving a case that the case did not contemplate. A badly designed bench gives a
number worth nothing, and the number *looks* objective.

## Language

Everything in this repository is in **English** — documents, code comments and the messages the
bench prints. The only exception is `PLAN-MAESTRO.md`, which stays in Spanish on purpose: it is the
internal planning document.