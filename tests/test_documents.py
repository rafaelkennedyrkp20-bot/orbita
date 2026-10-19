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


def _pdf_with_text(path, pages_text):
    """PDF com uma linha de texto por página, stream comprimido com Flate."""
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    for text in pages_text:
        page = writer.add_blank_page(width=600, height=800)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 700 Td (" + text.encode("latin-1") + b") Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream.flate_encode())
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def test_long_line_is_split_and_no_chunk_passes_the_limit(tmp_path):
    giant = {"text": "A" * (1024 * 1024), "page": 1, "section": ""}
    chunks = documents.chunk_segments([giant])
    assert chunks and len(chunks) <= documents.MAX_CHUNKS
    assert max(len(chunk["text"]) for chunk in chunks) <= documents.CHUNK_CHARS

    path = tmp_path / "linha.txt"
    path.write_text("palavra comprida " * 20_000 + "\ncurta\n", encoding="utf-8")
    rows, warning = documents.extract_document(path)
    assert warning is None
    chunks = documents.chunk_segments(rows)
    assert len(chunks) == documents.MAX_CHUNKS
    assert all(len(chunk["text"]) <= documents.CHUNK_CHARS for chunk in chunks)
    # A divisão respeita palavras quando há espaço.
    assert all(not chunk["text"].endswith("palav") for chunk in chunks)

    root = tmp_path / "index"
    assert documents.index_file(tmp_path, path, root=root) is None
    assert documents.search(tmp_path, "palavra comprida", root=root)


def test_small_pdf_with_huge_expansion_is_refused_with_a_clear_message(tmp_path):
    pdf = _pdf_with_text(tmp_path / "bomba.pdf", ["A" * (1024 * 1024)])
    assert pdf.stat().st_size < 16 * 1024
    rows, warning = documents.extract_document(pdf)
    assert rows == []
    assert warning and "limite" in warning.lower() and "página 1" in warning
    root = tmp_path / "index"
    note = documents.index_file(tmp_path, pdf, root=root)
    assert note == warning
    assert documents.search(tmp_path, "AAAA", root=root) == []


def test_many_pages_respect_page_and_document_quotas(tmp_path):
    normal = _pdf_with_text(tmp_path / "longo.pdf", [f"pagina numero {n} texto comum" for n in range(1, 46)])
    rows, warning = documents.extract_document(normal)
    assert warning is None
    assert max(row["page"] for row in rows) == documents.MAX_PAGES
    assert any("não foram lidas" in row["text"] for row in rows)
    assert all(len(c["text"]) <= documents.CHUNK_CHARS for c in documents.chunk_segments(rows))

    per_page = documents.MAX_DOC_CHARS // 30
    assert per_page < documents.MAX_PAGE_CHARS
    heavy = _pdf_with_text(tmp_path / "pesado.pdf", ["B " * (per_page // 2)] * 35)
    rows, warning = documents.extract_document(heavy)
    assert rows == []
    assert warning and "limite" in warning.lower() and "documento" in warning.lower()


def test_pdf_extraction_has_a_deadline(tmp_path, monkeypatch):
    pdf = _pdf_with_text(tmp_path / "lento.pdf", ["texto qualquer"] * 3)
    monkeypatch.setattr(documents, "MAX_EXTRACT_SECONDS", 0)
    rows, warning = documents.extract_document(pdf)
    assert rows == []
    assert warning and "tempo" in warning.lower()


def test_decompressed_stream_has_its_own_ceiling(tmp_path, monkeypatch):
    pdf = _pdf_with_text(tmp_path / "stream.pdf", ["C" * 50_000])
    monkeypatch.setattr(documents, "MAX_STREAM_BYTES", 4096)
    rows, warning = documents.extract_document(pdf)
    assert rows == []
    assert warning and "stream" in warning.lower()
