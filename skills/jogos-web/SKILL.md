---
name: jogos-web
description: Criar jogos que rodam no navegador com HTML, Canvas 2D ou Three.js, sem instalar nada, e testá-los com check_web_page (inclusive jogabilidade por script).
when: jogo no navegador, jogo HTML/JavaScript, canvas, three.js, jogo rápido sem instalar
---

# Jogos web (`jogos-web`)

O jeito mais leve de fazer jogo: abre com duplo clique no `index.html`, sem instalar nada.

## Estrutura
- `index.html` (canvas + HUD), `style.css`, `js/jogo.js` (loop), `js/entidades.js`, `assets/`.
- Sem CDN quando der (o jogo deve abrir offline). Three.js: baixe `three.module.min.js` para `js/vendor/` e importe como módulo
  — módulos ES exigem servidor; se precisar, avise o usuário ou use Canvas 2D.

Personagens e cenário: retângulo colorido só como provisório. Para sprites de verdade use a skill `modelagem-3d`
(seção "Personagem e sprites de jogo") ou imagens geradas, e confira o visual com `screenshot: true`.

## Esqueleto do loop (Canvas 2D)
```js
const tela = document.getElementById("tela"), ctx = tela.getContext("2d");
const teclas = new Set(); addEventListener("keydown", e => teclas.add(e.key)); addEventListener("keyup", e => teclas.delete(e.key));
const jogador = { x: 100, y: 100, v: 220 };
let antes = performance.now();
function quadro(agora) {
  const dt = Math.min(0.05, (agora - antes) / 1000); antes = agora;
  if (teclas.has("ArrowRight")) jogador.x += jogador.v * dt;
  if (teclas.has("ArrowLeft"))  jogador.x -= jogador.v * dt;
  ctx.clearRect(0, 0, tela.width, tela.height);
  ctx.fillStyle = "#22d3ee"; ctx.fillRect(jogador.x, jogador.y, 32, 32);
  requestAnimationFrame(quadro);
}
requestAnimationFrame(quadro);
window.estadoDoJogo = () => ({ x: jogador.x, y: jogador.y });   // gancho para teste
```
Deixe sempre um gancho `window.estadoDoJogo()` para o teste automático.

## Testar (obrigatório)
1. `check_web_page` em `index.html`: 0 erros de JavaScript, sem vazamento no celular (`width=390`).
2. Jogabilidade por script:
```
script: "dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight'}));
         await new Promise(r => setTimeout(r, 500));
         dispatchEvent(new KeyboardEvent('keyup', {key: 'ArrowRight'}));
         return window.estadoDoJogo()"
```
   O resultado tem que mostrar que o jogador se mexeu.
3. `screenshot: true` para conferir o visual.

## Controles no celular
Se for para celular, adicione botões na tela (touch) e teste com `width=390`.
