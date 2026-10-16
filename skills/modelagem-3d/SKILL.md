---
name: modelagem-3d
description: Criar modelos 3D — peças e objetos por código no OpenSCAD (leve) ou cenas, materiais, render e exportação GLB/FBX no Blender sem janela — sempre com imagem de prévia para conferir.
when: modelo 3D, objeto para impressão 3D, STL, GLB, cena 3D, render 3D, asset 3D para jogo
---

# Modelagem 3D (`modelagem-3d`)

## Escolha
- **OpenSCAD** (~22 MB): objetos geométricos, peças, impressão 3D, coisas paramétricas. Tudo é código `.scad`.
- **Blender** (~400 MB): cenas, personagens simples, materiais/cores, iluminação, render bonito, exportar GLB/FBX para jogos (Godot/Three.js).
- Antes, `toolbox_list`. Se faltar, `toolbox_install id="openscad"` ou `id="blender"` (pede permissão; o Blender é grande — prefira OpenSCAD se der conta).
- Use sempre o **caminho completo** do executável que o `toolbox_list` mostra. No PowerShell: `& "C:\...\openscad.com" ...`.

## OpenSCAD
1. Escreva `modelo.scad` (unidades em mm). Ex.:
```scad
$fn = 64;
difference() {
  cube([40, 40, 10], center = true);
  cylinder(h = 12, d = 20, center = true);
}
```
2. Exporte e gere prévia:
```
openscad.com -o modelo.stl modelo.scad
openscad.com -o previa.png --imgsize=800,600 --viewall --autocenter modelo.scad
```
3. Confira `previa.png` com `read_file`. Ajuste e repita até ficar certo.

## Blender sem janela
1. Escreva `cena.py` com `bpy` (o Blender roda o script e sai):
```python
from pathlib import Path
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(0, 0, 1))
obj = bpy.context.active_object
mat = bpy.data.materials.new("Cor"); mat.use_nodes = True
mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.2, 0.6, 1.0, 1)
obj.data.materials.append(mat)
bpy.ops.object.light_add(type="SUN", location=(4, -4, 6))
bpy.ops.object.camera_add(location=(5, -5, 4), rotation=(1.1, 0, 0.785))
scene = bpy.context.scene; scene.camera = bpy.context.active_object
scene.render.engine = "BLENDER_EEVEE_NEXT"; scene.render.resolution_x, scene.render.resolution_y = 800, 600
scene.render.filepath = str(Path.cwd() / "previa.png")
bpy.ops.render.render(write_still=True)
bpy.ops.export_scene.gltf(filepath=str(Path.cwd() / "modelo.glb"))
```
2. Rode: `blender.exe -b -P cena.py` **na pasta do projeto**. Caminhos sempre com `Path.cwd()` ou absolutos: sem .blend salvo, `//` vira a raiz do disco (C:\).
   Se `BLENDER_EEVEE_NEXT` não existir na versão, use `BLENDER_EEVEE` ou `CYCLES` (mais lento).
3. Confira `previa.png` com `read_file` e o tamanho do `modelo.glb`.

## Personagem e sprites de jogo (qualidade)
Primitivas soltas com luz padrão ficam com cara de "bonecos de bolinha" (caso real: cubo como bolsa, palitos
como pernas, cores estouradas). Comece pelo modelo testado: `use_skill name="modelagem-3d" file="personagem_toon.py"`
e troque só as partes. Ele já faz:
- **Suave**: Subdivision Surface (nível 2) + sombreamento suave em todas as partes orgânicas.
- **Toon de 2 tons** (Diffuse → Shader to RGB → ColorRamp constante): luz e sombra chapadas, sem plástico.
- **Contorno** escuro por casco invertido (Solidify com normais invertidas + material com backface culling).
- `view_transform = "Standard"` (sem lavar/estourar as cores), câmera **ortográfica**, fundo transparente.

Regras de forma:
- Proporção chibi: cabeça ≈ 45% da altura, olhos grandes (branco + pupila, com contorno fino), mãos e pés como
  esferas achatadas. Partes **encostadas/afundadas** umas nas outras, nada flutuando, nada de cubo cru.
- Paleta de 3–4 cores por personagem, com sombra de matiz mais fria/escura (não só preto). Inimigo com cor oposta.
- Mesma câmera, escala e luz para todos os sprites. Animação: 2–4 quadros mudando pose (pernas/braços girando),
  não só a posição; junte numa folha com `magick montage q*.png -tile 4x1 -geometry +0+0 -background none folha.png`.

Revise a prévia antes de entregar (`read_file` na imagem): silhueta legível em 64 px? contorno aparece? cores sem
estourar? partes conectadas? Se o seu modelo não enxerga imagens, peça a um ajudante com visão ou ao principal.

## Verificar sempre
- Toda entrega 3D tem uma **imagem de prévia** conferida visualmente.
- Para jogos: GLB pequeno (poucos polígonos), escala em metros, origem no chão.
