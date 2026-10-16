"""Checagem de integração da equipe: o caso real do site em que HTML e CSS usaram nomes diferentes."""

import time

from agent.core import integration

HTML = """<header class="site-header"><div class="wrap"><h1 class="logo">Jogos</h1></div></header>
<main><section class="secao-titulo">Top</section><div class="grade-jogos">
<article class="cartao"><div class="cartao-corpo"><a class="botao-jogar" id="jogar1">Jogar</a></div></article>
</div><input id="busca"></main>"""
CSS = """/* contrato do agente do CSS */
.header { position: fixed; top: 0 } .container { max-width: 1200px }
.btn { cursor: pointer } .card-body { padding: 16px 18px } .grid { display: grid }
@media (max-width: 600px) { .grid { grid-template-columns: 1fr } }"""
JS = """document.getElementById('busca').oninput = filtrar;
document.querySelector('#resultado').textContent = '';
card.classList.add('is-hidden'); el.classList.toggle('ativo');"""


def _files(tmp_path, html=HTML, css=CSS, js=JS):
    (tmp_path / "index.html").write_text(html, encoding="utf-8")
    (tmp_path / "style.css").write_text(css, encoding="utf-8")
    (tmp_path / "app.js").write_text(js, encoding="utf-8")


def test_mismatched_contract_is_reported(tmp_path):
    since = time.time() - 5
    _files(tmp_path)
    report = integration.check_workspace(tmp_path, since)
    assert "classes do HTML sem nenhum estilo" in report and ".site-header" in report
    assert "classes do CSS que não aparecem" in report and ".card-body" in report
    assert "#resultado" in report and "#busca" not in report        # busca existe, resultado não
    assert ".ativo" in report                                        # JS usa classe que ninguém define
    assert "nomes diferentes para os mesmos componentes" in report


def test_coherent_site_is_silent(tmp_path):
    html = '<header class="header"><div class="container"><a class="btn" id="busca">x</a></div></header>'
    css = ".header{} .container{} .btn{} .btn:hover{} .is-open{}"
    js = "document.getElementById('busca'); menu.classList.add('is-open')"
    _files(tmp_path, html, css, js)
    assert integration.check_workspace(tmp_path, time.time() - 5) == ""


def test_elements_created_by_js_are_not_false_alarms(tmp_path):
    """Caso real (rodada com DeepSeek): o JS cria o #toast e monta os cards em template string."""
    html = '<header class="header"><span id="cart-count"></span></header><main id="grid"></main>'
    css = ".header{} .toast{} .card{} .card-body{} .btn-add{} .show{}"
    js = """function toast(m){ let el = document.getElementById("toast");
      if(!el){ el = document.createElement("div"); el.id = "toast"; el.className = "toast"; } el.classList.add("show"); }
    const card = j => `<article class="card"><div class="card-body"><button class="btn-add">+</button></div></article>`;
    document.getElementById("grid").innerHTML = card({}); document.getElementById("cart-count");"""
    _files(tmp_path, html, css, js)
    assert integration.check_workspace(tmp_path, time.time() - 5) == ""


def test_old_files_and_non_web_projects_are_ignored(tmp_path):
    _files(tmp_path)
    assert integration.check_workspace(tmp_path, time.time() + 60) == ""   # nada mudou depois
    assert integration.check([], [tmp_path / "style.css"], []) == ""
