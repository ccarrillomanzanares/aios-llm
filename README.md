# aios-llm

Un LLM pequeño que **quepa en CPU** y sea el asistente de **AIOS**, no de Linux en general.

AIOS es **Linux From Scratch + `sven`**: `apt`, `dnf` y `pacman` **no existen** ahí, y ningún
modelo público ha visto eso. Cualquier modelo responde mal a la tarea más frecuente de un
asistente de sistema — instalar y gestionar software — y eso no se arregla con más parámetros.

## El problema que resuelve

Hoy, antes de cada respuesta, hay que darle al modelo un system prompt de **11.881 caracteres**
más 29 esquemas de herramienta. En CPU eso cuesta **~96 s el primer turno de una sesión** y ~6 s
los siguientes, que es la caché de prefijo de `llama-server` haciendo su trabajo con un prefijo
idéntico que se repite en cada petición.

El objetivo no es «saber más»: es **internalizar el contrato en los pesos** para poder servir con
un prompt de ~800 tokens. Por eso se mide TTFT y tokens de prompt antes y después.

## Estado medido

| | Multi-paso | Un paso |
|---|---|---|
| Banco de evaluación (29 casos × 6 idiomas) | **173/174 = 99,4 %** | 154/174 = 88,5 % |
| Trampas de seguridad | **53/54 = 98 %** | 50/54 = 93 % |
| Tareas verificadas por ejecución real | **12/12** | — |

Modelo medido: **Qwen3.6-35B-A3B** (el que sirve hoy en producción). Ese número es el **listón**
que tiene que superar el modelo pequeño en el dominio AIOS para integrarse. Si no lo supera, el
resultado sigue valiendo: el 35B se queda, y aquí está el número que lo demuestra.

**Multi-paso no es un detalle de implementación**: con el mismo modelo, medir en un solo paso da
**11 puntos menos**. Un banco de una petición → una respuesta puntúa mal a un agente que trabaja
en varios pasos, y el error no se ve: parece que falla el modelo.

## Cómo está montado

| | |
|---|---|
| `bateria/` | El banco de evaluación: casos, ejecutor, arneses y el **contrato real de producción** |
| `bateria/ejecutor.py` | Traduce las 29 herramientas de `aios-agent` a órdenes reales contra el oráculo |
| `bateria/repuntuar.py` | Re-puntúa una corrida ya hecha cuando el fallo era del instrumento |
| `oracle/oracle.sh` | El oráculo: una copia desechable de AIOS (chroot + overlay) |
| `auditoria/` | Auditoría de la capa de permisos de `aios-agent` y su batería de no-regresión |
| `ESTADO.md` | **El documento vivo del proyecto**: qué está hecho, qué se midió y qué falta |

### El oráculo

Un `chroot` sobre el rootfs extraído del squashfs de la ISO publicada, con el árbol base en
**solo lectura** y una capa de escritura desechable encima. Es la misma versión que tienen los
usuarios, y el caudal medido es de **0,17 s por ciclo de escritura + reset**.

```bash
sudo oracle/oracle.sh setup            # monta (idempotente)
sudo oracle/oracle.sh run -- "CMD"     # ejecuta SIN resetear
sudo oracle/oracle.sh reset            # tira la capa desechable
sudo oracle/oracle.sh verify           # integridad: 8 comprobaciones
```

Nada se ejecuta sin `verify` antes y después: **un banco que no se comprueba fabrica datos
falsos en silencio**, que en un proyecto de «dataset verificado por ejecución» es el peor
resultado posible.

## Dos reglas del proyecto

> **«El fichero bueno existe» ≠ «el fichero que se ejecuta es el bueno».**

Se verifica el md5 **en la máquina que EJECUTA**, no solo en la de origen, y un md5 que no
cuadra no se ignora: se para y se arregla.

> **Un caso que falla es una HIPÓTESIS, no un veredicto.**

Antes de apuntar un fallo al modelo, **leer la llamada real**. En la primera corrida completa,
**6 de los 7 fallos eran del instrumento**: un patrón de cadena prohibida que cazaba de más, y
formas válidas de resolver un caso que el caso no contemplaba. Un banco mal diseñado da un número
que no vale nada, y el número *parece* objetivo.