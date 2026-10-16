---
name: creative-pipeline
description: Pipeline estruturado para criação visual e multimídia (imagens, ícones, UI assets, storyboards e vídeos) com shot lists, keyframes e consistência de estilo.
---

# Creative Pipeline: Image, Video & Composite Workflows (`creative-pipeline`)

## Overview
Orquestra a criação de ativos visuais (imagens isoladas, séries consistentes, storyboards, ícones/UI e workflows de vídeo) combinando engenharia de contexto visual, `generate_image`, metadados de consistência (`.meta.json`) e automação por código/FFmpeg quando aplicável.

## When to Use
- Criação de imagens, ilustrações, logos, ícones ou mockups (`generate_image`).
- Criação de múltiplas cenas/imagens que exigem **consistência visual** (mesmo personagem, paleta, iluminação ou direção de arte).
- Produção de storyboards, animações, vídeos compostos ou apresentações visuais (combinando keyframes + script Python/FFmpeg/HTML).

## Process

### 1. Brief Visual & Style Bible (Anchor)
Antes de gerar qualquer ativo, defina o **Style Anchor** (âncora de estilo) que será reutilizado em todos os prompts da sessão:
- **Sujeito / Identidade**: traços físicos fixos, vestuário, formas geométricas, materiais.
- **Direção de Arte**: estilo (ex.: *cinematic 35mm, flat vector icon, dark glassmorphism UI, isometric 3D*), paleta de cores (hex/nomes), iluminação e atmosfera.
- **Enquadramento e Formato**: proporção (`1024x1024`, `1536x1024` landscape, `1024x1536` portrait), lente e ângulo de câmera.
- **Restrições (Negative/Avoid)**: elementos indesejados (ex.: texto ilegível, marcas d'água, fundo poluído).

### 2. Shot List & Keyframes (Para Séries ou Vídeo)
Quando o pedido envolver >1 imagem, narrativa visual ou vídeo, estruture uma **Shot List** antes de gerar:
| Shot # | Papel (Keyframe) | Ação / Composição | Tamanho | Arquivo de Saída |
|---|---|---|---|---|
| `shot_01` | Establishing / Hook | Plano aberto situando ambiente e iluminação | `1536x1024` | `shot_01_establishing.png` |
| `shot_02` | Sujeito Principal | Plano médio com foco na ação central | `1536x1024` | `shot_02_action.png` |
| `shot_03` | Detalhe / Fechamento | Close-up dramático ou tela final | `1536x1024` | `shot_03_close.png` |

### 3. Execução com Metadados de Consistência
Ao chamar `generate_image`:
- Passe o `prompt` combinando `[Style Anchor Fixo] + [Descrição Específica do Shot]`.
- Preencha `style` (âncora de estilo reutilizável), `negative_prompt` e `shot_id` quando disponíveis para persistir o sidecar `.meta.json` junto à imagem.
- Para séries independentes, chame `generate_image` e inspecione o resultado visualmente (com `read_file` em modelos com visão) para validar aderência ao Style Anchor antes de prosseguir.

### 4. Composição e Pós-Processamento (Código + Mídia)
- **Ativos de Software (Ícones/SVG/UI)**: Se o ativo exigir precisão geométrica (ex.: `.ico` multi-tamanho, gráficos vetoriais), combine geração ou código Python (`Pillow` / SVG) e valide dimensões e transparência.
- **Montagem de Vídeo / Slideshow**: Quando o usuário pedir vídeo a partir dos keyframes, use `run_shell` com `ffmpeg` (ou script Python) para compor os keyframes gerados com transições suaves, zoom (Ken Burns) ou áudio TTS, salvando o `.mp4` final e exibindo no painel com `show_file`.

## Common Rationalizations to Reject
- *"Vou mandar um prompt curto como 'um gato bonito'"* → Prompts vagos produzem resultados genéricos e inconsistentes. Especifique sujeito, composição, luz, paleta e estilo.
- *"Vou gerar 5 cenas mudando totalmente as palavras do estilo em cada uma"* → Isso destrói a continuidade entre shots. Mantenha o prefixo/sufixo do **Style Anchor** idêntico em todos os shots da mesma obra.
- *"Não preciso verificar a imagem gerada"* → Confirme que o arquivo existe, tem tamanho válido (>0 bytes) e chame `show_file` para apresentá-lo ao usuário.

## Red Flags
- Gerar múltiplos shots de uma história sem antes definir a Shot List e o Style Anchor.
- Ignorar proporção (`size`) adequada ao meio (ex.: usar quadrado para vídeo widescreen `1536x1024` ou vertical `1024x1536`).
- Esquecer de salvar em `save_to` quando o usuário especificou pasta/nome de arquivo.

## Verification
1. Todos os arquivos gerados existem no disco com tamanho > 0 bytes.
2. Em workflows multi-shot, cada ativo possui seu registro/sidecar ou segue exatamente o Style Anchor definido.
3. O resultado final foi apresentado ao usuário via `show_file` (ou preview automático).
