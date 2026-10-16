---
name: video-ffmpeg
description: Editar vídeo e áudio com FFmpeg — cortar, juntar, converter, comprimir, extrair áudio, fazer GIF, juntar imagens em vídeo — conferindo a duração e o resultado com ffprobe.
when: vídeo, áudio, cortar ou juntar vídeo, converter mp4, gif, extrair áudio, comprimir
---

# Vídeo e áudio com FFmpeg (`video-ffmpeg`)

## Preparar
- `toolbox_list`: se o FFmpeg já estiver no sistema (PATH), use-o. Senão `toolbox_install id="ffmpeg"` (~35 MB, Windows; no Linux, peça ao usuário `sudo apt install ffmpeg`).
- O `ffprobe` fica na mesma pasta do `ffmpeg`. Use caminhos completos no PowerShell: `& "C:\...\ffmpeg.exe" ...`.
- Nunca sobrescreva o original: saída com nome novo (`-n` recusa sobrescrever).

## Receitas
- Cortar sem recodificar (rápido): `ffmpeg -n -ss 00:00:10 -to 00:00:25 -i entrada.mp4 -c copy corte.mp4`
- Converter/comprimir: `ffmpeg -n -i entrada.mov -c:v libx264 -crf 23 -preset medium -c:a aac -b:a 128k saida.mp4`
- Diminuir resolução: `ffmpeg -n -i entrada.mp4 -vf scale=1280:-2 -c:a copy menor.mp4`
- Extrair áudio: `ffmpeg -n -i entrada.mp4 -vn -c:a libmp3lame -q:a 2 audio.mp3`
- Juntar vídeos (mesmo formato): crie `lista.txt` com linhas `file 'a.mp4'` e rode
  `ffmpeg -n -f concat -safe 0 -i lista.txt -c copy junto.mp4`
- GIF de qualidade: `ffmpeg -n -i entrada.mp4 -vf "fps=12,scale=480:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" saida.gif`
- Imagens → vídeo: `ffmpeg -n -framerate 24 -i quadro_%03d.png -c:v libx264 -pix_fmt yuv420p video.mp4`
- Quadro de prévia: `ffmpeg -n -ss 3 -i video.mp4 -frames:v 1 previa.png`

## Verificar sempre
- `ffprobe -v error -show_entries format=duration,size -of default=nw=1 saida.mp4` (duração e tamanho esperados).
- Extraia um quadro (`previa.png`) e confira com `read_file`.
- Vídeos longos: rode com `timeout` maior no `run_shell` (até 900 s).
