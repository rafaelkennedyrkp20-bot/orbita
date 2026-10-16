---
name: jogos-godot
description: Criar jogos 2D/3D no Godot 4 escrevendo os arquivos do projeto (project.godot, cenas .tscn, scripts GDScript) e validando pela linha de comando, sem abrir o editor.
when: jogo no Godot, GDScript, cena .tscn, jogo 2D ou 3D instalável
---

# Jogos com Godot (`jogos-godot`)

Para jogo simples que roda no navegador sem instalar nada, prefira a skill `jogos-web`.

## Preparar
- `toolbox_list`; se faltar, `toolbox_install id="godot"` (~86 MB, pede permissão). Use o executável **_console** que a ferramenta mostra (ele imprime erros no terminal).

## Estrutura mínima (escreva os arquivos)
`project.godot`:
```
config_version=5
[application]
config/name="Meu Jogo"
run/main_scene="res://main.tscn"
[display]
window/size/viewport_width=1280
window/size/viewport_height=720
```
`main.tscn` (cena com um nó raiz e script):
```
[gd_scene load_steps=2 format=3]
[ext_resource type="Script" path="res://main.gd" id="1"]
[node name="Main" type="Node2D"]
script = ExtResource("1")
```
`main.gd`:
```gdscript
extends Node2D
var velocidade := 300.0
func _process(delta: float) -> void:
    var dir := Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
    position += dir * velocidade * delta
```
Crie cenas e nós por código quando possível (`add_child`, `Sprite2D.new()`); `.tscn` à mão só para o essencial.

## Validar pela linha de comando
- Importar e checar erros: `Godot_console.exe --headless --path . --import`
- Rodar alguns quadros e sair: `Godot_console.exe --headless --path . --quit-after 120`
  (leia a saída: `SCRIPT ERROR`/`ERROR` = corrigir antes de seguir)
- Teste de lógica: um script `tests/teste.gd` com `extends SceneTree` + `func _init(): ...; quit()` e
  `Godot_console.exe --headless --path . --script res://tests/teste.gd`
- Exportar exige templates de exportação (download grande do próprio Godot): só se o usuário pedir.

## Assets
- 3D: skill `modelagem-3d` (Blender → `.glb`, o Godot importa direto).
- 2D/sprites: `generate_image` + skill `editar-imagem` para recortar/montar sprite sheet.

## Entrega
Explique como abrir (`Godot.exe --path <pasta>` ou importar no editor) e liste os controles do jogo.
