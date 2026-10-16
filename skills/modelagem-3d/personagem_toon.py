"""Modelo de personagem estilizado para jogo (Blender 4.x, sem janela): toon de 2 tons, contorno e sprite.

Rode na pasta do projeto: blender -b -P personagem_toon.py   → sprite.png (fundo transparente).
Troque as partes (cabeça, corpo, olhos, pés) pelo personagem pedido; mantenha toon(), parte() e a câmera.
"""
from pathlib import Path

import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


def toon(nome, cor, sombra):
    """Cor chapada com 2 tons (luz/sombra) — visual de jogo, sem plástico estourado."""
    mat = bpy.data.materials.new(nome); mat.use_nodes = True
    nt = mat.node_tree; nt.nodes.clear()
    dif = nt.nodes.new("ShaderNodeBsdfDiffuse")
    rgb = nt.nodes.new("ShaderNodeShaderToRGB")
    ramp = nt.nodes.new("ShaderNodeValToRGB"); ramp.color_ramp.interpolation = "CONSTANT"
    ramp.color_ramp.elements[0].color = (*sombra, 1); ramp.color_ramp.elements[1].position = 0.35
    ramp.color_ramp.elements[1].color = (*cor, 1)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(dif.outputs[0], rgb.inputs[0]); nt.links.new(rgb.outputs[0], ramp.inputs[0])
    nt.links.new(ramp.outputs[0], out.inputs["Surface"])
    return mat


CONTORNO = bpy.data.materials.new("Contorno"); CONTORNO.use_nodes = True
CONTORNO.use_backface_culling = True
_n = CONTORNO.node_tree.nodes; _n.clear()
_e = _n.new("ShaderNodeEmission"); _e.inputs["Color"].default_value = (0.05, 0.04, 0.08, 1)
CONTORNO.node_tree.links.new(_e.outputs[0], _n.new("ShaderNodeOutputMaterial").inputs["Surface"])


def parte(obj, mat, sub=2, contorno=0.025):
    """Suaviza (Subdivision), aplica o material e o contorno (casco invertido)."""
    obj.data.materials.append(mat); obj.data.materials.append(CONTORNO)
    for p in obj.data.polygons: p.use_smooth = True
    if sub: m = obj.modifiers.new("Suave", "SUBSURF"); m.levels = m.render_levels = sub
    s = obj.modifiers.new("Contorno", "SOLIDIFY"); s.thickness = contorno; s.offset = 1
    s.use_flip_normals = True; s.material_offset = 1
    return obj


def esfera(loc, escala, mat, **kw):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, location=loc)
    o = bpy.context.active_object; o.scale = escala
    return parte(o, mat, **kw)


pele, olho_b, olho_p = toon("Pele", (1.0, 0.72, 0.25), (0.78, 0.40, 0.16)), toon("Branco", (1, 1, 1), (0.75, 0.78, 0.9)), toon("Pupila", (0.08, 0.06, 0.12), (0.02, 0.02, 0.04))
esfera((0, 0, 1.05), (0.62, 0.55, 0.6), pele)                         # cabeça grande (chibi)
esfera((0, 0, 0.42), (0.4, 0.34, 0.38), pele)                         # corpo menor
for x in (-0.22, 0.22):
    esfera((x, -0.48, 1.12), (0.16, 0.06, 0.2), olho_b, contorno=0.015)
    esfera((x, -0.53, 1.1), (0.07, 0.03, 0.1), olho_p, sub=1, contorno=0)
    esfera((x * 1.1, 0, 0.08), (0.16, 0.22, 0.09), toon("Pe", (0.45, 0.25, 0.6), (0.25, 0.12, 0.38)))

scene.view_settings.view_transform = "Standard"                      # cores fiéis, sem lavar/estourar
bpy.ops.object.light_add(type="SUN", rotation=(0.9, 0.2, -0.6)); bpy.context.active_object.data.energy = 3
bpy.ops.object.camera_add(location=(0, -6, 0.75), rotation=(1.5708, 0, 0))
cam = bpy.context.active_object; cam.data.type = "ORTHO"; cam.data.ortho_scale = 2.4; scene.camera = cam
scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
scene.render.film_transparent = True
scene.render.resolution_x = scene.render.resolution_y = 256
scene.render.filepath = str(Path.cwd() / "sprite.png")   # sem .blend salvo, "//" vira a raiz do disco
bpy.ops.render.render(write_still=True)
