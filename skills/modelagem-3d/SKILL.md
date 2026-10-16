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
scene.render.filepath = bpy.path.abspath("//previa.png")
bpy.ops.render.render(write_still=True)
bpy.ops.export_scene.gltf(filepath=bpy.path.abspath("//modelo.glb"))
```
2. Rode: `blender.exe -b -P cena.py` (na pasta do projeto; `//` = pasta do arquivo .blend ou a atual).
   Se `BLENDER_EEVEE_NEXT` não existir na versão, use `BLENDER_EEVEE` ou `CYCLES` (mais lento).
3. Confira `previa.png` com `read_file` e o tamanho do `modelo.glb`.

## Verificar sempre
- Toda entrega 3D tem uma **imagem de prévia** conferida visualmente.
- Para jogos: GLB pequeno (poucos polígonos), escala em metros, origem no chão.
