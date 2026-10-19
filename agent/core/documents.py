"""Perguntas a documentos locais. Trechos são dados, nunca instruções.

A busca usa um embedding local por hash de palavras (sem baixar modelo).
A chave do índice inclui o identificador, a dimensão e a versão do arquivo.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import zlib
from contextlib import nullcontext
from pathlib import Path

from agent.core.config import DATA_DIR

EMBED_ID = "hash-v2"
DIM = 256
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_PAGES = 40
MAX_CHUNKS = 80
CHUNK_CHARS = 700  # teto de cada chunk; segmentos maiores são divididos
# Cotas do PDF: o arquivo de 8 MB é comprimido e pode expandir muito.
MAX_PAGE_CHARS = 100_000  # texto de uma página (uma página A4 densa tem ~5 mil)
MAX_DOC_CHARS = 400_000  # texto somado de todas as páginas lidas
MAX_STREAM_BYTES = 16 * 1024 * 1024  # stream descomprimido (o padrão do pypdf é 75 MB)
MAX_EXTRACT_SECONDS = 30
_TOKEN = re.compile(r"[0-9A-Za-zÀ-ÿ]{3,}", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN.findall(text or "")]


def embed(text: str) -> list[float]:
    vector = [0.0] * DIM
    for token in _tokens(text):
        digest = zlib.crc32(token.encode("utf-8")) & 0xFFFFFFFF
        vector[digest % DIM] += 1.0
        vector[(digest // DIM) % DIM] += 0.5
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def extract_document(path: Path) -> tuple[list[dict], str | None]:
    """Devolve segmentos {text, page, section} ou um aviso se não houver texto."""
    path = Path(path)
    if not path.is_file():
        return [], "Arquivo não encontrado."
    if path.stat().st_size > MAX_FILE_BYTES:
        return [], "Arquivo grande demais para a biblioteca (limite de 8 MB)."
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        return _sections(text, page=1), None
    if suffix == ".pdf":
        return _pdf(path)
    return [], "Formato ainda não suportado. Use TXT, Markdown ou PDF com texto."


def _sections(text: str, page: int) -> list[dict]:
    rows, section = [], ""
    for line in text.splitlines():
        if line.startswith("#"):
            section = line.lstrip("#").strip()[:120]
            continue
        if line.strip():
            rows.append({"text": line.strip(), "page": page, "section": section})
    if not rows and text.strip():
        rows.append({"text": text.strip(), "page": page, "section": ""})
    return rows


def _count(value: int) -> str:
    return f"{value:,}".replace(",", ".")


class _QuotaExceeded(Exception):
    """Cota de extração estourada; a mensagem vai ao usuário."""


class _Budget:
    """Conta o texto antes de o pypdf montar a string da página.

    O pypdf engole exceções dentro de XObjects; por isso o erro fica guardado
    e é relançado depois da extração.
    """

    def __init__(self) -> None:
        self.deadline = time.monotonic() + MAX_EXTRACT_SECONDS
        self.doc = 0
        self.page = 0
        self.number = 0
        self.error: _QuotaExceeded | None = None

    def start_page(self, number: int) -> None:
        self.number, self.page = number, 0
        self.check_time()

    def check_time(self) -> None:
        if time.monotonic() >= self.deadline:
            self.fail(f"A leitura do PDF passou do tempo limite de {MAX_EXTRACT_SECONDS} s. Nada foi indexado.")

    def add(self, amount: int) -> None:
        self.page += amount
        self.doc += amount
        if self.page > MAX_PAGE_CHARS:
            self.fail(f"A página {self.number} do PDF passou do limite de {_count(MAX_PAGE_CHARS)} caracteres "
                      "de texto. Nada foi indexado.")
        if self.doc > MAX_DOC_CHARS:
            self.fail(f"O texto do documento passou do limite de {_count(MAX_DOC_CHARS)} caracteres "
                      "(PDF com expansão grande demais). Nada foi indexado.")

    def fail(self, message: str) -> None:
        self.error = self.error or _QuotaExceeded(message)
        raise self.error

    def before_operator(self, operator, operands, *_matrices) -> None:
        if self.error:
            raise self.error
        self.check_time()
        if operator in (b"Tj", b"TJ", b"'", b'"'):
            size = 0
            for operand in operands:
                for item in operand if isinstance(operand, list) else (operand,):
                    if isinstance(item, (str, bytes)):
                        size += len(item)
            if size:
                self.add(size)


def _pdf_limits():
    """Teto de descompressão por stream, só durante esta leitura (contextvar do pypdf)."""
    try:
        import dataclasses

        from pypdf import apply_configuration, get_configuration
    except ImportError:  # pypdf antigo: fica com os limites internos dele
        return nullcontext()
    names = {field.name for field in dataclasses.fields(get_configuration())}
    limits = {name: MAX_STREAM_BYTES for name in (
        "zlib_maximum_output_length", "lzw_maximum_output_length", "run_length_maximum_output_length",
        "brotli_maximum_output_length", "array_based_stream_maximum_output_length",
        "maximum_declared_stream_length",
    ) if name in names}
    return apply_configuration(**limits)


def _pdf(path: Path) -> tuple[list[dict], str | None]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return [], "PDF textual precisa do pacote pypdf. OCR não está incluído."
    try:
        from pypdf.errors import LimitReachedError
    except ImportError:  # pypdf antigo
        LimitReachedError = _QuotaExceeded
    try:
        with _pdf_limits():
            return _pdf_rows(PdfReader, path, LimitReachedError)
    except _QuotaExceeded as error:
        return [], str(error)


def _pdf_rows(PdfReader, path: Path, LimitReachedError) -> tuple[list[dict], str | None]:
    try:
        reader = PdfReader(str(path))
    except LimitReachedError:
        raise _QuotaExceeded("O PDF tem um stream grande demais depois de descomprimido. Nada foi indexado.")
    except Exception:
        return [], "Não foi possível abrir este PDF."
    if getattr(reader, "is_encrypted", False):
        return [], "PDF protegido por senha não é lido."
    budget = _Budget()
    rows = []
    total = min(len(reader.pages), MAX_PAGES)
    for index in range(total):
        budget.start_page(index + 1)
        try:
            text = reader.pages[index].extract_text(visitor_operand_before=budget.before_operator) or ""
        except _QuotaExceeded:
            raise
        except LimitReachedError:
            budget.fail(f"A página {index + 1} do PDF tem um stream grande demais depois de descomprimido. "
                        "Nada foi indexado.")
        except Exception:
            text = ""
        if budget.error:  # estourou dentro de um XObject, onde o pypdf engole a exceção
            raise budget.error
        # O mapa de fontes pode expandir um código em vários caracteres: confere o resultado também.
        budget.add(max(0, len(text) - budget.page))
        rows.extend(_sections(text, page=index + 1))
    if len(reader.pages) > MAX_PAGES:
        rows.append({"text": f"[páginas após {MAX_PAGES} não foram lidas]", "page": MAX_PAGES, "section": ""})
    if not any(row["text"] and not row["text"].startswith("[páginas") for row in rows):
        return [], "Este PDF não tem texto selecionável. Ele precisaria de OCR, que não está incluído."
    return rows, None


def _split(text: str):
    """Fatias de no máximo CHUNK_CHARS, cortando no último espaço quando houver."""
    start, end_of_text = 0, len(text)
    while end_of_text - start > CHUNK_CHARS:
        limit = start + CHUNK_CHARS
        cut = text.rfind(" ", start + 1, limit + 1)
        if cut <= start:
            cut = limit
        head = text[start:cut].strip()
        if head:
            yield head
        start = cut
    tail = text[start:].strip()
    if tail:
        yield tail


def chunk_segments(segments: list[dict]) -> list[dict]:
    """Agrupa segmentos em até MAX_CHUNKS chunks; nenhum passa de CHUNK_CHARS caracteres."""
    chunks, current, meta = [], [], None
    size = 0
    for segment in segments:
        info = {"page": segment.get("page") or 1, "section": segment.get("section") or ""}
        for piece in _split(segment.get("text") or ""):
            if size and size + len(piece) > CHUNK_CHARS:
                chunks.append({**meta, "text": " ".join(current)})
                if len(chunks) >= MAX_CHUNKS:
                    return chunks
                current, size = [], 0
            if not current:
                meta = info
            current.append(piece)
            size += len(piece) + 1
    if current and len(chunks) < MAX_CHUNKS:
        chunks.append({**meta, "text": " ".join(current)})
    return chunks


def _index_file(workspace: Path, root: Path) -> Path:
    digest = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:16]
    return root / digest / "index.json"


def _load_index(path: Path) -> dict:
    if not path.exists():
        return {"embed": EMBED_ID, "dim": DIM, "files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if data.get("embed") != EMBED_ID or data.get("dim") != DIM or not isinstance(data.get("files"), dict):
        return {"embed": EMBED_ID, "dim": DIM, "files": {}}
    return data


def _save_index(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def index_file(workspace: Path, file_path: Path, *, root: Path | None = None) -> str | None:
    root = root or (DATA_DIR / "doc_index")
    path = Path(file_path).resolve()
    segments, warning = extract_document(path)
    store = _index_file(workspace, root)
    data = _load_index(store)
    key = str(path)
    if warning or not segments:
        data["files"].pop(key, None)
        _save_index(store, data)
        return warning or "Sem texto para indexar."
    stat = path.stat()
    chunks = []
    for piece in chunk_segments(segments):
        chunks.append({**piece, "vector": embed(piece["text"])})
    data["files"][key] = {
        "mtime_ns": stat.st_mtime_ns, "size": stat.st_size, "chunks": chunks,
    }
    _save_index(store, data)
    return None


def search(workspace: Path, query: str, *, root: Path | None = None, limit: int = 5) -> list[dict]:
    """Trechos ordenados. Lista vazia significa ausência de evidência, não uma resposta inventada.

    O hash local colide entre palavras sem relação. Sem um token em comum, o trecho
    não é citado, mesmo que o cosseno fique positivo.
    """
    query = (query or "").strip()
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return []
    root = root or (DATA_DIR / "doc_index")
    data = _load_index(_index_file(workspace, root))
    needle = embed(query)
    scored = []
    stale = False
    for file_name, record in list(data.get("files", {}).items()):
        path = Path(file_name)
        if not path.is_file():
            data["files"].pop(file_name, None)
            stale = True
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime_ns != record.get("mtime_ns") or stat.st_size != record.get("size"):
            data["files"].pop(file_name, None)
            stale = True
            continue
        for chunk in record.get("chunks") or []:
            text = chunk.get("text") or ""
            if not query_tokens.intersection(_tokens(text)):
                continue
            vector = chunk.get("vector")
            if not isinstance(vector, list) or len(vector) != DIM:
                continue
            scored.append((_cosine(needle, vector), file_name, chunk))
    if stale:
        _save_index(_index_file(workspace, root), data)
    scored.sort(key=lambda item: -item[0])
    results = []
    for score, file_name, chunk in scored[:limit]:
        if score <= 0:
            continue
        results.append({
            "path": file_name,
            "page": chunk.get("page") or 1,
            "section": chunk.get("section") or "",
            "text": chunk.get("text") or "",
            "score": round(score, 4),
        })
    return results
