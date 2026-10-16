---
name: editar-imagem
description: Editar imagens existentes — redimensionar, recortar, converter formato, remover fundo simples, juntar sprites, marca d'água — com Pillow (já instalado) ou ImageMagick (caixa de ferramentas).
when: editar, redimensionar, recortar ou converter imagem existente; sprites
---

# Editar imagem (`editar-imagem`)

Para **criar** imagem do zero use `generate_image` (skill `creative-pipeline`). Esta skill é para **mexer** em imagem que já existe.

## Qual ferramenta
1. **Pillow** — já vem com o Órbita. Rode por `run_shell` com o Python do Órbita (`python -c` ou um script `.py` na pasta do projeto). Bom para tudo que é simples.
2. **ImageMagick** — mais rápido e com mais filtros. Veja com `toolbox_list`; se não estiver instalado e valer a pena (lote grande, efeitos), use `toolbox_install id="imagemagick"` (pede permissão ao usuário). No PowerShell chame com o caminho completo: `& "C:\...\magick.exe" ...`.

## Receitas (Pillow)
```python
from PIL import Image, ImageOps
img = Image.open("entrada.png")
img.thumbnail((1024, 1024))                      # redimensionar mantendo proporção
img.crop((x, y, x + w, y + h)).save("recorte.png")
img.convert("RGB").save("saida.jpg", quality=88)  # PNG → JPG
ImageOps.expand(img, border=16, fill="white").save("com_borda.png")
```
Remover fundo de cor sólida (fundo branco/verde):
```python
img = Image.open("entrada.png").convert("RGBA")
dados = [(r, g, b, 0) if r > 240 and g > 240 and b > 240 else (r, g, b, a) for r, g, b, a in img.getdata()]
img.putdata(dados); img.save("sem_fundo.png")
```
Sprite sheet (quadros do mesmo tamanho lado a lado):
```python
quadros = [Image.open(f"quadro_{i}.png") for i in range(8)]
w, h = quadros[0].size
folha = Image.new("RGBA", (w * len(quadros), h))
for i, q in enumerate(quadros): folha.paste(q, (i * w, 0))
folha.save("sprites.png")
```

## Receitas (ImageMagick)
- Redimensionar lote: `magick mogrify -path saida -resize 1024x1024> *.png`
- Converter: `magick entrada.png -quality 88 saida.webp`
- Sprite sheet: `magick montage quadro_*.png -tile 8x -geometry +0+0 -background none sprites.png`
- Remover fundo: `magick entrada.png -fuzz 8% -transparent white sem_fundo.png`

## Verificar sempre
- Abra o resultado com `read_file` (imagens voltam visualmente para modelos com visão) ou mostre com `show_file`.
- Confira dimensões e formato (`Image.open(p).size, .mode`) e que o original não foi sobrescrito sem pedido.
