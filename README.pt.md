# L2DropSpoilGen 1.3 — Ícones de Drop/Spoil ao passar o mouse (HighFive)

[English](README.md) · [Español](README.es.md) · **Português**

Adiciona um ícone de **Drop** (moeda de adena) e um de **Spoil** à janela de
alvo de cada monstro. Ao passar o mouse no ícone, aparece a **lista completa de
drop / spoil** daquele mob, com quantidades e chances, tirada direto do
datapack do seu servidor.

**100% client-side** — o servidor não é tocado: nada de java, scripts ou mods.
A ferramenta corrige 3 arquivos da pasta `System` do cliente:

| Arquivo | O que é adicionado |
|---|---|
| `npcgrp.dat` | um par `[skill_id, nível]` por ícone no `property_list` de cada mob |
| `SkillGrp.dat` | uma entrada por skill gerada (define o ícone) |
| `SkillName-<idioma>.dat` | uma entrada por skill gerada (o texto do tooltip) |

## Requisitos

- **Cliente:** Lineage 2 **High Five** (criptografia `.dat` `Lineage2Ver413`).
- **Datapack:** XMLs de NPC no estilo **L2J Mobius** (`data/stats/npcs/*.xml`
  com `<dropLists><drop>/<spoil>`). Os nomes dos itens vêm dos comentários do
  XML (os datapacks Mobius os têm), então saem em inglês.

## Uso

### Interface gráfica
Execute o `L2DropSpoilGen.exe` sem argumentos. A interface está em **inglês,
espanhol e português** (autodetectada do sistema; trocável no canto superior
direito) e cada campo tem um **tooltip de ajuda "?"**:

1. **Pasta NPCs do datapack** — o `data/stats/npcs` do seu datapack (a raiz do
   datapack também funciona).
2. **Pasta System do cliente** — a pasta `System` com os `npcgrp.dat`,
   `SkillGrp.dat`, `SkillName-*.dat` ORIGINAIS. Os idiomas detectados aparecem
   como caixas de seleção.
3. **Pasta de saída** — onde os 3 `.dat` corrigidos são escritos.
4. Clique em **Gerar**, faça **backup** dos originais na `System` e copie os
   arquivos gerados por cima. Pronto — entre no jogo e dê target em qualquer mob.

A interface lembra suas pastas e opções entre usos, e abre a pasta de saída ao
terminar.

### Linha de comando

```
L2DropSpoilGen.exe --npcs <datapack>\data\stats\npcs --system <cliente>\System --out patched
```

| Opção | Padrão | Significado |
|---|---|---|
| `--lang pt,e` | todos os encontrados | quais `SkillName-<idioma>.dat` corrigir |
| `--rates-ini <caminho>` | off | o `Rates.ini` do seu servidor — as chances/quantidades mostradas aplicam os **mesmos multiplicadores do servidor** (listas per-item, cascata herb/raid/normal, rates de spoil; itens com chance 0 são escondidos) |
| `--min-chance 0.01` | 0 (off) | esconder itens abaixo desta chance % |
| `--max-items 30` | 0 (off) | máximo de itens por lista (adiciona `+N more...`) |
| `--max-line 70` | 0 (off) | largura máxima da linha (nomes longos são encurtados) |
| `--max-chars 1500` | 1500 | tamanho máximo do tooltip |
| `--chance-decimals 2` | 4 | decimais das chances |
| `--title-drop` / `--title-spoil` | Drop / Spoil | títulos do cabeçalho |
| `--header-factor 0.95` | 1.0 | largura do cabeçalho em relação à linha mais larga |
| `--trunc-suffix` | `...(more)` | texto ao cortar uma lista |
| `--base-id 30001` | 30001 | primeiro id de skill gerado (mude em caso de colisão) |
| `--drop-icon` / `--spoil-icon` | adena / spoil | qualquer `icon.*` do cliente |

Rodar a ferramenta de novo sobre arquivos já corrigidos é seguro: ela detecta e
remove a geração anterior primeiro (mesmos ids/ícones), então você pode iterar
as opções de formato à vontade.

## Notas

- **Rates do servidor** (`--rates-ini` ou o campo "Rates.ini do servidor" na
  GUI): a ferramenta clona a cascata exata de rates de drop do L2J Mobius
  (`NpcTemplate.calculateDrops`) — primeiro
  `DropChance/AmountMultiplierByItemId`, depois herbs (itens
  `ex_immediate_effect`, detectados de `data/stats/items`), depois raid
  (`type="RaidBoss|GrandBoss"`), depois os multiplicadores Death normais; o
  spoil usa seus multiplicadores planos. Fatores por-jogador (premium,
  champion, diferença de nível, buffs de drop) são de runtime e não podem ser
  mostrados estaticamente.
- Os ids de skill gerados (`30001+`) estão bem acima do máximo retail do
  HighFive (26073). Se o seu servidor já usa skills de cliente nessa faixa,
  mude o `--base-id`.
- O texto do tooltip fica de propósito no campo **name** da skill: o campo
  description tem um limite de largura no cliente HF e quebra as linhas.
- A ferramenta se auto-verifica em cada passo (descriptografar → desmontar →
  remontar deve ser byte-idêntico antes de modificar qualquer coisa) e preserva
  o footer do `npcgrp.dat` — um "File was corrupted" não passa.
- **Antivírus:** o exe é empacotado com PyInstaller e alguns AVs dão falso
  positivo genérico. O código-fonte Python completo (`l2dropspoilgen.py`) está
  incluído — você pode auditar e rodar direto (`python l2dropspoilgen.py`,
  Python 3.8+, sem dependências).

## Créditos

- Toolchain `.dat` embutido: **l2encdec** e **l2asm/l2disasm** de
  **M.Soltys (DStuff)**, definições ddf da comunidade (czardadius e outros).
- Referência da estrutura do `npcgrp.dat`: editor **L2ClientDat**.
- Ferramenta de **Rekiem Games Network** (rekiemgames.com). Grátis
  para a comunidade; não vender.
