# L2DropSpoilGen 1.3 — Iconos de Drop/Spoil al pasar el ratón (HighFive)

[English](README.md) · **Español** · [Português](README.pt.md)

Añade un icono de **Drop** (moneda de adena) y otro de **Spoil** a la ventana de
target de cada monstruo. Al pasar el ratón por el icono se muestra la **lista
completa de drop / spoil** de ese mob, con cantidades y chances, sacada
directamente del datapack de tu servidor.

**100% del lado del cliente** — el servidor no se toca: nada de java, scripts
ni mods. La herramienta parchea 3 archivos de la carpeta `System` del cliente:

| Archivo | Qué se añade |
|---|---|
| `npcgrp.dat` | un par `[skill_id, nivel]` por icono en el `property_list` de cada mob |
| `SkillGrp.dat` | una entrada por skill generada (define el icono) |
| `SkillName-<idioma>.dat` | una entrada por skill generada (el texto del tooltip) |

## Requisitos

- **Cliente:** Lineage 2 **High Five** (cifrado `.dat` `Lineage2Ver413`).
- **Datapack:** XMLs de NPC estilo **L2J Mobius** (`data/stats/npcs/*.xml` con
  `<dropLists><drop>/<spoil>`). Los nombres de los items se leen de los
  comentarios del XML (los datapacks Mobius los traen), así que salen en inglés.

## Uso

### Interfaz gráfica
Ejecuta `L2DropSpoilGen.exe` sin argumentos. La interfaz está en **inglés,
español y portugués** (se autodetecta del sistema; conmutable arriba a la
derecha) y cada campo tiene un **tooltip de ayuda "?"**:

1. **Carpeta NPCs del datapack** — el `data/stats/npcs` de tu datapack (también
   vale la raíz del datapack).
2. **Carpeta System del cliente** — la carpeta `System` con los
   `npcgrp.dat`, `SkillGrp.dat`, `SkillName-*.dat` ORIGINALES. Los idiomas
   detectados aparecen como casillas.
3. **Carpeta de salida** — dónde se escriben los 3 `.dat` parcheados.
4. Pulsa **Generar**, haz **backup** de los originales de `System` y copia los
   archivos generados encima. Listo — entra al juego y targetea cualquier mob.

La interfaz recuerda tus carpetas y opciones entre usos, y abre la carpeta de
salida al terminar.

### Línea de comandos

```
L2DropSpoilGen.exe --npcs <datapack>\data\stats\npcs --system <cliente>\System --out patched
```

| Opción | Por defecto | Significado |
|---|---|---|
| `--lang es,e` | todos los encontrados | qué `SkillName-<idioma>.dat` parchear |
| `--rates-ini <ruta>` | off | el `Rates.ini` de tu servidor — los chances/cantidades mostrados aplican los **mismos multiplicadores que el servidor** (listas per-item, cascada herb/raid/normal, rates de spoil; los items con chance 0 se ocultan) |
| `--min-chance 0.01` | 0 (off) | ocultar items por debajo de este % de chance |
| `--max-items 30` | 0 (off) | máximo de items por lista (añade `+N more...`) |
| `--max-line 70` | 0 (off) | ancho máximo de línea (los nombres largos se acortan) |
| `--max-chars 1500` | 1500 | longitud máxima del tooltip |
| `--chance-decimals 2` | 4 | decimales de los porcentajes |
| `--title-drop` / `--title-spoil` | Drop / Spoil | títulos de la cabecera |
| `--header-factor 0.95` | 1.0 | ancho de la cabecera respecto a la línea más ancha |
| `--trunc-suffix` | `...(more)` | texto al recortar una lista |
| `--base-id 30001` | 30001 | primer id de skill generado (cámbialo si hay colisión) |
| `--drop-icon` / `--spoil-icon` | adena / spoil | cualquier `icon.*` del cliente |

Re-ejecutar la herramienta sobre archivos ya parcheados es seguro: detecta y
elimina primero la generación anterior (mismos ids/iconos), así que puedes
iterar las opciones de formato libremente.

## Notas

- **Rates del servidor** (`--rates-ini` o el campo "Rates.ini del servidor" de
  la GUI): la herramienta clona la cascada exacta de rates de drop de L2J
  Mobius (`NpcTemplate.calculateDrops`) — primero
  `DropChance/AmountMultiplierByItemId`, luego herbs (items
  `ex_immediate_effect`, detectados de `data/stats/items`), luego raid
  (`type="RaidBoss|GrandBoss"`), luego los multiplicadores Death normales; el
  spoil usa sus multiplicadores planos. Los factores por-jugador (premium,
  champion, diferencia de nivel, buffs de drop) son de runtime y no se pueden
  mostrar estáticamente.
- Los ids de skill generados (`30001+`) están muy por encima del máximo retail
  de HighFive (26073). Si tu servidor ya usa skills de cliente en ese rango,
  cambia `--base-id`.
- El texto del tooltip vive a propósito en el campo **name** de la skill: el
  campo description tiene un tope de ancho en el cliente HF y parte las líneas.
- La herramienta se auto-verifica en cada paso (descifrar → desensamblar →
  re-ensamblar debe ser byte-idéntico antes de modificar nada) y conserva el
  footer de `npcgrp.dat`, así que no puede colarse un "File was corrupted".
- **Antivirus:** el exe está empaquetado con PyInstaller y algunos AV dan un
  falso positivo genérico. El código fuente Python completo
  (`l2dropspoilgen.py`) va incluido — puedes auditarlo y ejecutarlo
  directamente (`python l2dropspoilgen.py`, Python 3.8+, sin dependencias).

## Créditos

- Toolchain `.dat` incluido: **l2encdec** y **l2asm/l2disasm** de
  **M.Soltys (DStuff)**, definiciones ddf de la comunidad (czardadius y otros).
- Referencia de la estructura de `npcgrp.dat`: editor **L2ClientDat**.
- Herramienta de **Rekiem Games Network** (rekiemgames.com). Gratis
  para la comunidad; no vender.
