"""Recuperação local com fonte. Sem evidência, não há citação."""

from pypdf import PdfWriter

from agent.core import documents


CORPUS = {
    "portao.md": """# Portão
O código do portão da oficina é 4312 e fica na rua das acácias.
# Estoque
O parafuso sextavado de bronze está na gaveta azul.
""",
    "receita.md": """# Bolo
A receita do bolo de laranja usa três ovos e raspas da casca.
# Café
O café da manhã da casa é coado com pó torrado em casa.
""",
    "viagem.md": """# Ônibus
A passagem para Olinda sai às sete da manhã na rodoviária central.
# Hotel
O hotel da viagem se chama Farol Baixo e fica na avenida do mar.
""",
    "projeto.md": """# Prazo
A entrega do módulo de notas é na sexta-feira dia vinte.
# Equipe
A revisora do texto se chama Nara e usa caneta verde.
""",
}

QUESTIONS = [
    ("código do portão da oficina", "4312", "portao.md"),
    ("parafuso sextavado de bronze", "gaveta azul", "portao.md"),
    ("bolo de laranja", "três ovos", "receita.md"),
    ("café da manhã", "pó torrado", "receita.md"),
    ("passagem para Olinda", "sete da manhã", "viagem.md"),
    ("hotel da viagem", "Farol Baixo", "viagem.md"),
    ("módulo de notas", "sexta-feira", "projeto.md"),
    ("revisora do texto", "Nara", "projeto.md"),
    ("rua das acácias", "4312", "portao.md"),
    ("raspas da casca", "laranja", "receita.md"),
    ("rodoviária central", "Olinda", "viagem.md"),
    ("avenida do mar", "Farol", "viagem.md"),
    ("caneta verde", "Nara", "projeto.md"),
    ("gaveta azul", "bronze", "portao.md"),
    ("dia vinte", "notas", "projeto.md"),
    ("torrado em casa", "café", "receita.md"),
    ("oficina", "portão", "portao.md"),
    ("Farol Baixo", "hotel", "viagem.md"),
    ("três ovos", "bolo", "receita.md"),
    ("sexta-feira dia vinte", "módulo", "projeto.md"),
]


def test_retrieval_cites_the_file_and_refuses_to_invent(tmp_path):
    root = tmp_path / "index"
    for name, text in CORPUS.items():
        file_path = tmp_path / name
        file_path.write_text(text, encoding="utf-8")
        assert documents.index_file(tmp_path, file_path, root=root) is None
    hits_ok = 0
    for query, snippet, name in QUESTIONS:
        found = documents.search(tmp_path, query, root=root, limit=5)
        assert found, query
        blob = " ".join(item["text"] for item in found)
        if snippet.lower() in blob.lower() and any(item["path"].endswith(name) for item in found):
            hits_ok += 1
        assert all(item["page"] and "path" in item for item in found)
    assert hits_ok >= 17
    assert documents.search(tmp_path, "qual é a senha do banco suíço", root=root) == []
    assert documents.search(tmp_path, "??", root=root) == []


def test_missing_file_drops_from_the_index_and_empty_pdf_needs_ocr(tmp_path):
    root = tmp_path / "index"
    path = tmp_path / "nota.md"
    path.write_text("# Nota\nO token interno é azul-47.\n", encoding="utf-8")
    documents.index_file(tmp_path, path, root=root)
    path.unlink()
    assert documents.search(tmp_path, "azul-47", root=root) == []
    pdf = tmp_path / "vazio.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with pdf.open("wb") as handle:
        writer.write(handle)
    rows, warning = documents.extract_document(pdf)
    assert rows == []
    assert warning and "OCR" in warning
