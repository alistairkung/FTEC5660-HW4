"""FTEC5660 Homework 4: the retrieval half of a RAG assistant over company reports.

Fill in the five functions marked ### YOUR CODE HERE. You may add imports, constants and helper
functions above them, but do not change the provided code below them (the models, the generator,
the loaders, the runner and the scoring).

    python3 hw4.py --data-folder public_test
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import threading
import time
import traceback
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.documents import Document
from langchain_deepseek import ChatDeepSeek

load_dotenv()


# =============================================================================
# Your code: add imports, constants and helper functions here.
# =============================================================================

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from textwrap import wrap

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from langchain_text_splitters.character import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi


@dataclass
class LexicalIndex:
    chunks: list[Document]
    ranker: BM25Okapi | None
    company_positions: dict[str, dict[str, list[int]]]
    children: dict[tuple[str, str], Document]


# Strip a single trailing legal suffix while preserving punctuation inside names.
COMPANY_SUFFIX = re.compile(r",? (?:inc|corp|corporation|ltd|limited|plc|llc|co)$")


def company_candidates(index: LexicalIndex, subjects: list[str]) -> tuple[set[int] | None, str]:
    """Return the union of positions, or a reason to use the global candidate pool."""
    if not subjects:
        return None, "no_subject"
    eligible: set[int] = set()
    for subject in subjects:
        key = COMPANY_SUFFIX.sub("", squash(subject).removesuffix("."))
        identities = index.company_positions.get(key, {})
        if not identities:
            return None, "unresolved"
        if len(identities) > 1:
            return None, "ambiguous"
        eligible.update(next(iter(identities.values())))
    return eligible, "resolved"


def ranked_positions(index: LexicalIndex, question: str) -> list[int]:
    positions = range(len(index.chunks))
    if index.ranker is None:
        return list(positions)
    # The global sort also inherits BM25's tie order before candidate restriction.
    return index.ranker.get_top_n(question.lower().split(), positions, n=len(positions))


FINANCIAL_CELL = re.compile(
    r"^\s*[^:|]+:\s*\(?[+−-]?\s*(?:[$€£]\s*)?"
    r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*%?\)?\s*$"
)


def row_terms(text: str) -> str:
    return " ".join(re.findall(r"[^\W\d_]+", squash(text)))


def has_matched_financial_row(chunk: Document, query: str) -> bool:
    for line in chunk.page_content.splitlines():
        label, separator, fields = line.partition("|")
        terms = row_terms(label) if separator else ""
        if terms and f" {terms} " in query and any(
            FINANCIAL_CELL.fullmatch(field) for field in fields.split("|")
        ):
            return True
    return False


def rank_financial_rows(index: LexicalIndex, ranking: list[int], question: str) -> list[int]:
    """Prefer chunks with a literal query mention of a numeric table row label."""
    query = f" {row_terms(question)} "
    matching = []
    remaining = []
    for position in ranking:
        group = matching if has_matched_financial_row(index.chunks[position], query) else remaining
        group.append(position)
    return matching + remaining


def allocate_comparison(index: LexicalIndex, ranking: list[int]) -> list[int]:
    """Reserve the first chunk per company when all companies fit in the budget."""
    first_by_company: dict[str, int] = {}
    unique_positions: list[int] = []
    seen: set[int] = set()
    for position in ranking:
        chunk = index.chunks[position]
        if id(chunk) in seen:
            continue
        seen.add(id(chunk))
        unique_positions.append(position)
        company = squash(chunk.metadata["company"]).removesuffix(".")
        first_by_company.setdefault(company, position)

    if len(first_by_company) < 2:
        return ranking[:MAX_RETRIEVED]
    if len(first_by_company) > MAX_RETRIEVED:
        # The full union stays eligible when there are too few slots to guarantee coverage.
        return unique_positions[:MAX_RETRIEVED]

    reserved = set(first_by_company.values())
    remaining = [position for position in unique_positions if position not in reserved]
    selected = reserved.union(remaining[:MAX_RETRIEVED - len(reserved)])
    return [position for position in unique_positions if position in selected]


def company_phrase(name: str) -> str:
    return rf"(?<!\w){re.escape(name)}(?!\w)"


def clearly_absent_subject(index: LexicalIndex, question: str, subject: str) -> bool:
    name = squash(subject).removesuffix(".")
    text = squash(question)
    phrase = company_phrase(name)
    subject_role = rf"{phrase}[’']s?\s|\bdid\s+{phrase}\.?\s+(?!and\b|or\b)[a-z]+"
    if not re.search(subject_role, text):
        return False
    # A known name elsewhere in the question or a literal mention in the corpus
    # can indicate a partial parse, an alias, or supporting material.
    if any(re.search(company_phrase(key), text) for key in index.company_positions if key):
        return False
    indexed_positions = sum(len(positions) for identities in index.company_positions.values()
                            for positions in identities.values())
    return indexed_positions == len(index.chunks) and not any(
        re.search(phrase, squash(chunk.page_content)) for chunk in index.chunks
    )


def abstention_reason(
    index: LexicalIndex, question: str, parsed: dict, resolution: str
) -> str | None:
    subjects = parsed["companies"]
    if resolution == "unresolved" and len(subjects) == 1:
        if clearly_absent_subject(index, question, subjects[0]):
            return "absent_company"

    year = parsed.get("fiscal_year")
    if resolution != "resolved" or parsed.get("doc_type") != "annual_report" or year is None:
        return None
    if {int(match[1]) for match in FISCAL_YEAR.finditer(question)} != {year}:
        return None

    year_text = re.compile(rf"(?<!\d){year}(?!\d)|\bFY\s*['’]?{year % 100:02d}\b", re.I)
    for subject in subjects:
        positions, _ = company_candidates(index, [subject])
        if not positions:
            continue
        company_chunks = [index.chunks[position] for position in positions]
        report_years = [chunk.metadata.get("fiscal_year") for chunk in company_chunks
                        if chunk.metadata.get("doc_type") == "annual_report"]
        # Protect the oldest report's implicit prior-year comparative column and
        # explicit historical references anywhere in the company's indexed text.
        if (report_years and all(type(value) is int for value in report_years)
                and year < min(report_years) - 1
                and not any(chunk.metadata.get("fiscal_year") == year
                            or year_text.search(chunk.page_content) for chunk in company_chunks)):
            return "unsupported_historical_period"
    return None


def report_metadata(file_name: str, soup: BeautifulSoup) -> dict[str, str | int]:
    title = soup.title.get_text(" ", strip=True)
    company = soup.h1.get_text(" ", strip=True).split(" (", 1)[0]
    report_types = (
        ("annual_report", r"Annual Report\s+(\d{4})"),
        ("earnings_call", r"Full Year\s+(\d{4})\s+Earnings Call"),
        ("research_report", r"FY\s*(\d{4})\s+results review"),
    )
    for doc_type, pattern in report_types:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            return {
                "source": file_name,
                "company": company,
                "fiscal_year": int(match[1]),
                "doc_type": doc_type,
            }
    raise ValueError(f"Unrecognised report title in {file_name}: {title!r}")


def cell_span(cell: Tag, attribute: str) -> int:
    try:
        span = max(1, int(cell.get(attribute, 1)))
        return min(span, 1000) if attribute == "colspan" else span
    except (TypeError, ValueError):
        return 1


def table_headers(rows: list[list[Tag]]) -> dict[int, str]:
    """Associate each physical column with its sequence of group and leaf headers."""
    labels: dict[int, list[str]] = {}
    occupied_until: dict[int, int] = {}
    for level, cells in enumerate(rows):
        column = 0
        for cell in cells:
            while occupied_until.get(column, 0) > level:
                column += 1
            end = column + cell_span(cell, "colspan")
            text = " ".join(cell.get_text().split())
            for i in range(column, end):
                occupied_until[i] = level + cell_span(cell, "rowspan")
                if text:
                    labels.setdefault(i, []).append(text)
            column = end
    return {i: " ".join(parts) for i, parts in labels.items()}


# Allow name-internal punctuation and legal suffixes without consulting the corpus.
NAME_WORD = r"[A-Z][\w]*(?:[-'’][A-Z][\w]*)*"
COMPANY_MENTION = re.compile(
    rf"\b{NAME_WORD}(?:\s+(?:(?:&|of(?: the)?)\s+)?{NAME_WORD})*"
    r"(?:,?\s+(?i:plc|ltd|inc|corp|llc)\b)?\.?"
)
MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
FISCAL_YEAR = re.compile(
    rf"\b(?:FY\s*|fiscal\s+year\s+|\d{{1,2}}\s+{MONTH}\s+|{MONTH}\s+\d{{1,2}},?\s+|"
    r"(?:in|for|of|during)\s+|(?<=['’]s )|(?<=s['’] )|"
    r"(?=(?:19|20)\d{2}\s+(?:revenue|income|profit|cash|sales|assets|earnings)\b))"
    r"((?:19|20)\d{2})\b", re.I
)
EARNINGS_CALL = r"earnings[- ](?:conference[- ])?calls?"
REPORT_NOUN = rf"(?:annual report|results review|{EARNINGS_CALL})"


def subject_companies(question: str) -> list[str]:
    # Mask time, units and interrogative framing before matching capitalized spans.
    text = FISCAL_YEAR.sub(" ", question)
    text = re.sub(r"\b(?:Q[1-4]|USD|HKD|EUR|GBP|CEO|CFO)\b", " ", text)
    text = re.sub(r"^\s*(?:who|what|when|where|which|how|compare|between|using|at|in|on|"
                  r"did|does|is|were|was|has|have)\b", "", text, flags=re.I)

    mentions = []
    for match in COMPANY_MENTION.finditer(text):
        before, after = text[:match.start()], text[match.end():]
        # Names acting as the source of a rating, forecast or audit are intermediaries.
        if re.search(r"\b(?:according to|audited by|issued by|rated by)\s*$", before, re.I):
            continue
        intermediary_verb = re.match(r"\s+(?:audit(?:s|ed)?|forecast(?:s|ed)?|predict(?:s|ed)?|"
                                     r"rat(?:es|ed)|gives?|sets?|assigns?)\b", after, re.I)
        if intermediary_verb and COMPANY_MENTION.search(after):
            continue
        if re.match(r"['’]s\s+(?:target price|price target|rating|forecast|audit opinion)"
                    r"\b.*?\b(?:for|on|of)\b", after, re.I):
            continue
        mentions.append(match)

    if not mentions:
        return []
    # A comparison can introduce its subjects after a colon. Otherwise look for
    # coordination at the first name to avoid collecting lists of segments or regions.
    comparison = re.search(r"\b(?:which|between|compare|versus|vs|more|higher|lower|fewer)\b",
                           question, re.I)
    for start in range(len(mentions) if comparison else 1):
        group = [mentions[start][0]]
        for left, right in zip(mentions[start:], mentions[start + 1:]):
            separator = text[left.end():right.start()].strip().lower()
            if separator == ",":
                group.append(right[0])
            elif separator.lstrip(",").strip() in {"or", "and", "versus", "vs", "vs."}:
                return [*group, right[0]]
            else:
                break

    for match in mentions:
        if re.match(r"['’](?:s\b|(?=\s))", text[match.end():]):
            return [match[0]]
    for match in mentions:
        if re.search(r"\b(?:did|does|is|was|for|audited|give|of)\s*$", text[:match.start()], re.I):
            return [match[0]]
    return [mentions[0][0]]


def table_to_text(table_html: str) -> str:
    """Task 1.1: turn one HTML <table> into text that keeps every value with its row and its column.

    Put each value on a line (at most 400 characters) together with its row label and its column
    header, e.g. "Revenue | 2025: 2,710.4 | 2024: 2,629.1", one table row per line, keep the text of
    every cell unchanged, and include the caption (it holds the unit) in the output. Do not call the
    LLM here.
    """
    ### YOUR CODE HERE
    table = BeautifulSoup(table_html, "html.parser").find("table")
    if table is None:
        return ""
    for br in table.find_all("br"):
        br.replace_with(" ")
    lines = [table.caption.get_text().strip()] if table.caption else []
    header_rows: list[list[Tag]] = []
    headers: dict[int, str] = {}
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if not cells:
            continue
        values = [" ".join(cell.get_text().split()) for cell in cells]
        if row.find_parent("thead") or (len(cells) > 1 and all(
                cell.name == "th" and cell.get("scope") != "row" for cell in cells)):
            header_rows.append(cells)
            lines.append(" | ".join(filter(None, values)))
            continue
        if header_rows:
            headers = table_headers(header_rows)
            header_rows.clear()

        label = line = values[0]
        column = cell_span(cells[0], "colspan")
        for cell, value in zip(cells[1:], values[1:]):
            end = column + cell_span(cell, "colspan")
            names = dict.fromkeys(headers[i] for i in range(column, end) if i in headers)
            column = end
            if not value:
                continue
            field = f"{' / '.join(names)}: {value}" if names else value
            candidate = f"{line} | {field}" if line else field
            if len(candidate) > MAX_LINE_CHARS and line != label:
                lines.append(line)
                candidate = f"{label} | {field}" if label else field
            line = candidate
        if line:
            lines.append(line)
    # An indivisible label/header/value triple can itself exceed the scoring limit.
    # Preserve its text across lines in that case.
    bounded_lines = []
    for line in lines:
        if len(line) > MAX_LINE_CHARS:
            bounded_lines.extend(wrap(line, MAX_LINE_CHARS, break_on_hyphens=False))
        else:
            bounded_lines.append(line)
    return "\n".join(bounded_lines)


@dataclass(frozen=True)
class Topic:
    aliases: re.Pattern[str]
    disclosure: re.Pattern[str]


AUDIT = Topic(
    re.compile(r"\b(?:audit(?:s|ed|or|ors|ing)?|account(?:ing|ancy) firms?|statutory assurance)\b"),
    re.compile(r"\b(?:audited|audits|appoint\w*|engag\w*|succeed\w*|replac\w*|signed|"
               r"served|opinion|was|were|is)\b"),
)
BUYBACK = Topic(
    re.compile(r"\b(?:buy[- ]?backs?|repurchas(?:e|es|ed|ing)|stock reacquisition)\b"),
    re.compile(r"\b(?:approv\w*|authori[sz]\w*|announc\w*|launch\w*|capp?ed|up to)\b"),
)
OFFICERS = (
    Topic(re.compile(r"\b(?:cfo|chief financial officer|finance chief)\b"),
          re.compile(r"\b(?:appoint\w*|serv\w*|succeed\w*|became|is|was|named|title)\b")),
    Topic(re.compile(r"\b(?:ceo|chief executive officer|chief executive)\b"),
          re.compile(r"\b(?:appoint\w*|serv\w*|succeed\w*|became|is|was|named|title)\b")),
)
TOPICS = (AUDIT, BUYBACK, *OFFICERS)

CURRENCY_AMOUNT = re.compile(
    r"(?:\b(?:usd|hkd|eur|gbp)\s*|[$€£]\s*)\d|\b\d[\d,.]*\s+(?:million|billion|shares)\b"
)
HYPOTHETICAL_OR_NEGATED = re.compile(r"\b(?:not|never|no|may|might|could|if|whether)\b")
# Keep reference-only occurrences in inventories, conversation prompts and question sentences weak.
REFERENCE_ONLY = re.compile(
    r"^(?:who|what|which|how|where|when)\b|"
    r"\b(?:index|agenda|table of contents|refer to|see page|for example|unrelated company)\b"
)
AUDIT_FIRM_SUFFIX = re.compile(r"\b(?:llp|llc|ltd|plc|partners|associates)\b")
MAY_DATE = re.compile(r"\b\d{1,2} may\b|\bmay \d{1,2}\b")
MAX_HEADING_WORDS = 8


def sentence_windows(text: str) -> tuple[tuple[str, str], ...]:
    """Return narrow prose windows with an adjacent heading when visible in the same chunk."""
    windows: list[tuple[str, str]] = []
    heading = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line.split()) <= MAX_HEADING_WORDS and not re.search(r"[.?!;:|]", line):
            heading = line
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            windows.append((heading, sentence))
    return tuple(windows)


def prose_signal(
    text: str, topic: Topic, requested_year: int | None
) -> tuple[int, int, int]:
    """Return evidence support, stated year and location of the topic match."""
    terms = topic.aliases
    best = (0, 0, 0)
    for heading, sentence in sentence_windows(text):
        local_match = bool(terms.search(sentence))
        if not local_match and not terms.search(heading):
            continue
        if sentence.endswith("?") or REFERENCE_ONLY.search(sentence):
            continue
        if HYPOTHETICAL_OR_NEGATED.search(MAY_DATE.sub("", sentence)) or not topic.disclosure.search(sentence):
            continue
        if topic is BUYBACK and not CURRENCY_AMOUNT.search(sentence):
            continue
        support = 2 if topic is AUDIT and AUDIT_FIRM_SUFFIX.search(sentence) else 1
        year = bool(requested_year and re.search(rf"(?<!\d){requested_year}(?!\d)", sentence))
        best = max(best, (support, int(year), int(local_match)))
    return best


def promote_prose(
    index: LexicalIndex, question: str, parsed: dict, eligible_order: list[int], parents: list[Document]
) -> list[Document]:
    """Promote one original prose passage, using the unpartitioned V6 BM25 order for ties."""
    query = squash(question)
    topics = [topic for topic in TOPICS if topic.aliases.search(query)]
    if len(topics) != 1:
        return parents
    kind = parsed["doc_type"]
    if kind == "annual_report" and has_matched_financial_row(parents[0], f" {row_terms(question)} "):
        return parents

    year = parsed["fiscal_year"]
    best_score = (0, 0, 0, 0, 0)
    best = None
    for position in eligible_order:
        chunk = index.chunks[position]
        support, stated_year, local_match = prose_signal(chunk.page_content.casefold(), topics[0], year)
        if not support:
            continue
        score = (support, stated_year, int(year is not None and chunk.metadata["fiscal_year"] == year),
                 int(chunk.metadata["doc_type"] == kind), local_match)
        if score > best_score:
            best_score, best = score, chunk
    if best is None or best is parents[0]:
        return parents
    return [best, *[chunk for chunk in parents if chunk is not best]][:MAX_RETRIEVED]


CELL_CHILD = "_research_scoped_cell"
YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})([AEFP])?(?![A-Za-z\d])", re.I)
ESTIMATE = re.compile(r"\b(?:forecast|estimates?|projected|guidance)\b", re.I)
SCOPED_CAPTION = re.compile(
    r"^([\w][\w -]*?)\s+by\s+(?:(?:business|geographic(?:al)?|delivery|sales)\s+)?"
    r"(?:regions?|segments?|markets?|divisions?|channels?)\b", re.I,
)
CELL_UNIT = re.compile(
    r"\b(?:usd|hkd|eur|gbp|jpy|cny|thousands?|millions?|billions?|units?|shares?|employees)\b|[$€£¥%]",
    re.I,
)
CONSTANT_CURRENCY = re.compile(r"\bconstant[\s-]+currency\b", re.I)
COMPOUND_REQUEST = re.compile(
    r"\b(?:and|or|versus|vs|plus|also|alongside|combined|sum|difference|both|each|respectively|"
    r"change|growth|increas\w*|decreas\w*|ratio|margin|share|percent(?:age)?)\b"
)


@dataclass(frozen=True)
class Cell:
    label: str
    column: str
    field: str
    caption: str
    metric: str

    def actual_year(self) -> int | None:
        periods = YEAR.findall(self.column)
        if len(periods) != 1 or ESTIMATE.search(self.column):
            return None
        number, suffix = periods[0]
        return int(number) if suffix.upper() in {"", "A"} else None

    @property
    def text(self) -> str:
        return f"{self.caption}\n{self.label} | {self.field}"


def cells(text: str) -> Iterator[Cell]:
    """Read V6-rendered numeric cells, keeping scope only within a local caption."""
    caption = metric = ""
    for line in text.splitlines():
        match = SCOPED_CAPTION.match(line)
        if match:
            caption, metric = line, match[1]
            continue
        label, separator, fields = line.partition("|")
        if not separator:
            caption = metric = ""
            continue
        for raw in fields.split("|"):
            if FINANCIAL_CELL.fullmatch(raw):
                field = raw.strip()
                column = field.partition(":")[0].strip()
                yield Cell(label.strip(), column, field, caption, metric)


def query_phrase(value: str, terms: str) -> bool:
    phrase = row_terms(value)
    return bool(phrase) and f" {phrase} " in terms


def query_terms(question: str, subjects: list[str]) -> str:
    terms = f" {row_terms(question)} "
    for subject in subjects:
        terms = terms.replace(f" {row_terms(subject)} ", " ")
    return terms


def metric_outside_scope(cell: Cell, terms: str) -> bool:
    without_scope = terms.replace(f" {row_terms(cell.label)} ", " ", 1)
    return query_phrase(cell.metric, without_scope)


def explicit_year(question: str, parsed: dict) -> int | None:
    year = parsed.get("fiscal_year")
    if year is not None and {int(match[1]) for match in FISCAL_YEAR.finditer(question)} == {year}:
        return year
    return None


def narrow_financial_passage(
    index: LexicalIndex, question: str, parsed: dict, parents: list[Document]
) -> list[Document]:
    """Replace the earliest eligible parent with a child emitted during ingestion."""
    year = explicit_year(question, parsed)
    if not index.children or parsed["doc_type"] != "annual_report" or year is None:
        return parents
    terms = query_terms(question, parsed["companies"])
    if not terms.startswith((" what was ", " what were ", " what is ", " what are ", " how much ")):
        return parents

    requested_basis = bool(CONSTANT_CURRENCY.search(question))
    for slot, parent in enumerate(parents):
        matched = [cell for cell in cells(parent.page_content)
                   if cell.actual_year() == year and query_phrase(cell.label, terms)
                   and metric_outside_scope(cell, terms)]
        if len(matched) != 1:
            continue
        cell = matched[0]
        unbound = terms
        for name in (cell.label, cell.metric):
            unbound = unbound.replace(f" {row_terms(name)} ", " ", 1)
        if COMPOUND_REQUEST.search(unbound):
            continue
        child = index.children.get((parent.metadata["source"], cell.text))
        if child is not None and (not requested_basis or CONSTANT_CURRENCY.search(child.page_content)):
            return [*parents[:slot], child, *parents[slot + 1:]]
    return parents


def chunk_document(file_name: str, html: str) -> list[Document]:
    """Task 1.2: split one document into chunks of at most MAX_CHUNK_CHARS characters.

    Every chunk needs the metadata "source" (= file_name), "company", "fiscal_year" (an int) and
    "doc_type" (one of DOC_TYPES). Do not call the LLM here.
    """
    ### YOUR CODE HERE
    soup = BeautifulSoup(html, "html.parser")
    metadata = report_metadata(file_name, soup)
    child_texts: dict[str, None] = {}
    for table in soup.find_all("table"):
        rendered = table_to_text(str(table))
        table.replace_with("\n" + rendered + "\n")
        if metadata["doc_type"] == "annual_report":
            for cell in cells(rendered):
                # Keep the full parent when the label, header and caption cannot carry the unit.
                if (cell.metric and cell.actual_year() is not None and len(cell.text) <= MAX_CHUNK_CHARS
                        and CELL_UNIT.search(cell.text)):
                    child_texts[cell.text] = None
    splitter = RecursiveCharacterTextSplitter(chunk_size=MAX_CHUNK_CHARS, chunk_overlap=200)
    parents = splitter.create_documents([soup.get_text()], [metadata])
    children = [Document(page_content=text, metadata={**metadata, CELL_CHILD: True}) for text in child_texts]
    attach_headings(soup, parents)
    return parents + children


def parse_query(question: str) -> dict:
    """Task 2.2: {"companies": [names], "fiscal_year": int or None, "doc_type": one of DOC_TYPES}.

    The rules for each field are under Task 2.2 in the handout. You may use make_llm() here.
    """
    ### YOUR CODE HERE
    years = list(FISCAL_YEAR.finditer(question))
    # A dated source can introduce a question about a different reporting period.
    requested = next((y for y in years if not re.match(rf"\s+{REPORT_NOUN}\b",
                                                       question[y.end():], re.I)), None)
    year = requested or next(iter(years), None)
    if re.search(rf"\b{EARNINGS_CALL}\b", question, re.I):
        kind = "earnings_call"
    elif re.search(r"\b(?:ratings?|target prices?|price targets?|forecast(?:s|ed)?|predict(?:s|ed)?|results reviews?)\b",
                   question, re.I):
        kind = "research_report"
    else:
        kind = "annual_report"
    return {"companies": subject_companies(question), "fiscal_year": int(year[1]) if year else None,
            "doc_type": kind}


def build_index(chunks: list[Document]) -> LexicalIndex:
    """Task 2: index the chunks of the whole corpus (the output of chunk_document), once per run.

    Return anything retrieve() needs: a BM25 or TF-IDF index, the chunks grouped by metadata, ...
    """
    ### YOUR CODE HERE
    parents = []
    children = {}
    for chunk in chunks:
        if chunk.metadata.get(CELL_CHILD):
            children[(chunk.metadata["source"], chunk.page_content)] = chunk
        else:
            parents.append(chunk)
    tokens = [chunk.page_content.lower().split() for chunk in parents]
    ranker = BM25Okapi(tokens) if any(tokens) else None
    companies: dict[str, dict[str, list[int]]] = {}
    for position, chunk in enumerate(parents):
        company = chunk.metadata.get("company")
        if isinstance(company, str) and company.strip():
            identity = squash(company).removesuffix(".")
            key = COMPANY_SUFFIX.sub("", identity)
            companies.setdefault(key, {}).setdefault(identity, []).append(position)
    return LexicalIndex(parents, ranker, companies, children)


CHUNK_OVERLAP = 200  # C+B RecursiveCharacterTextSplitter overlap setting.
HISTORICAL_YEAR = re.compile(r"(?<![\d,.])(?:19|20)\d{2}(?!\d|[.,]\d)")
SHORT_YEAR = re.compile(r"\bFY\s*['’]?(\d{2})(?!\d)", re.I)
FINANCIAL = re.compile(
    r"\b(?:revenue|sales|turnover|earnings|income|profit|loss|cash|assets?|liabilit\w*|equity|"
    r"debt|borrow\w*|credit facilit\w*|receivables?|payables?|inventor\w*|expenses?|"
    r"costs?|capex|expenditure|investments?|repurchas\w*|dividends?|refund\w*|"
    r"rent|lease|balance sheet|financ\w*|monetary|amounts?|payout\w*|margin)\b", re.I,
)
UNIT = re.compile(r"\b(?:USD|HKD|EUR|GBP|US dollars?)\s+(?:millions?|billions?|thousands?)\b", re.I)
NUMBER_TEXT = r"(?<![\w,.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\d|[.,]\d)"
NUMBER = re.compile(NUMBER_TEXT)
CURRENCY = re.compile(
    rf"(?:\b(?:USD|HKD|EUR|GBP)\s*|[$€£]\s*)[(−-]?{NUMBER_TEXT}|"
    rf"{NUMBER_TEXT}\s*(?:million|billion|thousand)?\s+(?:US dollars?|USD|HKD|EUR|GBP)\b", re.I,
)
SCALE = re.compile(rf"{NUMBER_TEXT}\s+(?:million|billion|thousand)\b", re.I)
COUNT_UNIT = re.compile(
    r"^\s*(?:%|percent\b|bps\b|people\b|employees?\b|directors?\b|members?\b|"
    r"sites?\b|stores?\b|units?\b|facilities\b|projects?\b|offices?\b|customers?\b|"
    r"vehicles?\b|plant(?:s)?\b|weeks?\b|days?\b|hours?\b|months?\b|years?\b|"
    r"tonnes?\b|ton\b|items?\b|countries\b|deliveries\b|orders\b|shares\b|locations?\b|"
    r"branches\b|shipments?\b|contracts?\b|depots?\b|miles?\b|incidents?\b)", re.I,
)
UNRELATED = re.compile(
    r"\b(?:director since|in role since|appointed|joined|reappointed|served|elected|tenure|"
    r"found(?:ed|ing)|incorporated|established|headcount|employees?|staff|attendance|"
    r"sites?|stores?|facilities|shipments?|units?|orders?|vehicles?|projects?|"
    r"offices?|branches|countries|customers?|people|members|meetings|days|hours|"
    r"tonnes|incidents|production volume)\b", re.I,
)
GOVERNANCE = re.compile(r"\b(?:corporate governance|board of directors|executive officers|board responsibilities)\b", re.I)
CONTINUATION = re.compile(
    r"^\s*(?:on |upon |at (?:that|the same) time\b|that (?:year|period|balance|amount)\b|"
    r"in (?:that|the same) (?:year|period)\b|the (?:figure|amount|balance|total)\b|"
    r"this (?:amount|figure|balance|included)\b|as a result\b|it (?:was|stood|totalled|amounted)\b)", re.I,
)
FISCAL_REFERENCE = r"(?:the\s+)?(?:(?:FY|fiscal(?:\s+year)?)\s*)?(?P<anchor>(?:19|20)\d{2})"
DIRECTION = r"(?P<direction>before|preceding|prior to|after|following)"
COUNT_WORD = r"(?P<count>one|two|three|four|five|six|seven|eight|nine|ten|[1-9])"
COUNT_WORDS = dict(zip("one two three four five six seven eight nine ten".split(), range(1, 11)))
RELATIVE_ANCHOR = re.compile(
    rf"\b(?:{COUNT_WORD}\s+(?:full\s+)?(?:fiscal\s+|financial\s+)?years?\s+|"
    rf"(?:the\s+)?(?:first\s+)?(?:full\s+)?(?:fiscal\s+|financial\s+|reporting\s+)?"
    rf"year\s+(?:immediately\s+)?){DIRECTION}\s+{FISCAL_REFERENCE}", re.I,
)
RELATIVE_FILING = re.compile(
    rf"\b{COUNT_WORD}\s+(?:fiscal\s+|financial\s+)?years?\s+{DIRECTION}\s+"
    r"(?:this|the)\s+(?:report(?:ing)?|filing|current fiscal)\s+(?:year|period)\b", re.I,
)
PRIOR_FILING = re.compile(r"\b(?:prior|previous|preceding|comparable|comparative)\s+(?:fiscal\s+|financial\s+)?(?:year|period)\b", re.I)
EVENT_PERIOD = re.compile(
    r"\b(?:historical (?:baseline|balance|figure|results?)|inception|back then|"
    r"(?:fiscal |financial |full )?year (?:in which|of (?:the|his|her)|(?:immediately )?(?:before|after|following|preceding))|"
    r"(?:first|last) (?:full )?(?:year|reporting period) (?:of|in|before|after|following)|"
    r"years? (?:ago|earlier|before|after|prior)|at (?:the time of|appointment)|"
    r"(?:before|after|upon) (?:the |our |his |her )?(?:appointment|refinanc\w*|commission\w*|"
    r"restructur\w*|divest\w*|merger|acquisition|takeover|reorganisation))\b", re.I,
)
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z“])")
SECTION = re.compile(r"^\s*\d{1,2}\.\s+")
NON_ACTUAL = re.compile(r"\b(?:forecast|projected|estimate)\b", re.I)
DAY_MONTH = re.compile(rf"\b(?:\d{{1,2}}\s+{MONTH}|{MONTH}\s+\d{{1,2}})\b", re.I)


@dataclass(frozen=True)
class HistoricalDecision:
    reason: str | None
    route: str
    source: str = ""
    passage: str = ""


def period(text: str, filing_year: int) -> tuple[set[int], bool]:
    """Identify printed periods and a few anchored relative constructions."""
    years = set()
    remaining = text
    for pattern in (RELATIVE_ANCHOR, RELATIVE_FILING):
        matches = list(pattern.finditer(remaining))
        for match in matches:
            offset = match["count"] or "one"
            offset = int(offset) if offset.isdigit() else COUNT_WORDS[offset.lower()]
            anchor = int(match["anchor"]) if pattern is RELATIVE_ANCHOR else filing_year
            earlier = match["direction"].lower() in {"before", "preceding", "prior to"}
            years.add(anchor - offset if earlier else anchor + offset)
        remaining = pattern.sub(" ", remaining)
    years.update(int(match[0]) for match in HISTORICAL_YEAR.finditer(remaining))
    years.update(filing_year // 100 * 100 + int(match[1]) for match in SHORT_YEAR.finditer(remaining))
    # A printed year owns its sentence. Read bare comparative language relative
    # to the filing only when the sentence supplies no competing time anchor.
    unresolved = bool(EVENT_PERIOD.search(remaining)) and not years
    if not years and not unresolved and PRIOR_FILING.search(remaining):
        years.add(filing_year - 1)
    return years, unresolved


def reconstructed(chunks: list[Document]) -> str:
    """Join original source-ordered parents for internal analysis only."""
    parts = []
    previous = ""
    for chunk in chunks:
        text = chunk.page_content
        overlap = next((n for n in range(min(len(previous), len(text), CHUNK_OVERLAP), 39, -1)
                        if previous.endswith(text[:n])), 0)
        parts.append(text[overlap:] if overlap else "\n" + text)
        previous = text
    return "".join(parts)


def heading(text: str) -> bool:
    return len(text) <= 150 and (bool(SECTION.match(text)) or not text.endswith((".", "?", "!", ";")))


def money(text: str, monetary_heading: bool, financial_context: bool) -> bool:
    if CURRENCY.search(text):
        return True
    if not financial_context:
        return False
    if any(not COUNT_UNIT.match(text[m.end():]) for m in SCALE.finditer(text)):
        return True
    if not monetary_heading:
        return False
    without_dates = DAY_MONTH.sub(" ", SHORT_YEAR.sub(" ", HISTORICAL_YEAR.sub(" ", text)))
    return any(not COUNT_UNIT.match(without_dates[m.end():]) for m in NUMBER.finditer(without_dates))


def table_years(line: str) -> set[int]:
    years = set()
    for field in line.split("|")[1:]:
        if FINANCIAL_CELL.fullmatch(field):
            label = field.partition(":")[0]
            for year, suffix in YEAR.findall(label):
                if suffix.upper() in {"", "A"} and not NON_ACTUAL.search(label):
                    years.add(int(year))
    return years


def scan_source(text: str, filing_year: int, wanted: int) -> tuple[str, bool, bool]:
    """Return a veto passage, an unclear old-year mention, and comparative coverage."""
    in_governance = False
    monetary_heading = financial_heading = False
    heading_period: tuple[set[int], bool] = (set(), False)
    previous_period: tuple[set[int], bool] = (set(), False)
    unclear = coverage = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "|" in line:
            years = table_years(line)
            financial_row = financial_heading or bool(FINANCIAL.search(line.partition("|")[0]))
            coverage |= financial_row and {filing_year - 1, filing_year} <= years
            if wanted in years and financial_row:
                return line, unclear, coverage
            if HISTORICAL_YEAR.search(line) and wanted in period(line, filing_year)[0]:
                unclear |= not (in_governance or UNRELATED.search(line))
            previous_period = (set(), False)
            continue
        if heading(line):
            if SECTION.match(line) or GOVERNANCE.search(line):
                in_governance = bool(GOVERNANCE.search(line))
            monetary_heading = bool(UNIT.search(line))
            financial_heading = bool(FINANCIAL.search(line)) or monetary_heading
            heading_period = period(line, filing_year)
            previous_period = (set(), False)
            # A short line may itself contain a dated amount.
        for sentence in SENTENCE.split(line):
            dates, unresolved = period(sentence, filing_year)
            if not dates and not unresolved:
                dates, unresolved = previous_period if CONTINUATION.search(sentence) and any(previous_period) else heading_period
            financial_context = financial_heading or bool(FINANCIAL.search(sentence))
            if (wanted in dates or unresolved) and money(sentence, monetary_heading, financial_context):
                return sentence, unclear, coverage
            if wanted in dates and not (in_governance or UNRELATED.search(sentence)):
                unclear = True
            previous_period = dates, unresolved
    return "", unclear, coverage


def historical_gap_policy(index: LexicalIndex, question: str, parsed: dict,
                      eligible: set[int] | None, resolution: str) -> HistoricalDecision:
    year = explicit_year(question, parsed)
    if year is None or resolution != "resolved" or len(parsed["companies"]) != 1 or parsed["doc_type"] != "annual_report":
        return HistoricalDecision(abstention_reason(index, question, parsed, resolution), "existing")
    documents = defaultdict(list)
    for position in sorted(eligible or ()):
        chunk = index.chunks[position]
        documents[chunk.metadata["source"]].append(chunk)
    filings = {source: (chunks[0].metadata["doc_type"], chunks[0].metadata["fiscal_year"])
               for source, chunks in documents.items()}
    annuals = sorted(year for kind, year in filings.values() if kind == "annual_report")
    if not annuals or year >= annuals[0] - 1:
        return HistoricalDecision(abstention_reason(index, question, parsed, resolution), "existing")
    unclear = False
    covered_annuals = 0
    for source, chunks in documents.items():
        kind, reporting_year = filings[source]
        hit, possible, coverage = scan_source(reconstructed(chunks), reporting_year, year)
        if hit:
            # This branch precedes even the evaluation of the original veto.
            return HistoricalDecision(None, "historical_evidence_veto", source, hit)
        unclear |= possible
        covered_annuals += kind == "annual_report" and coverage
    complete = (len(annuals) == 2 and annuals[1] == annuals[0] + 1 and covered_annuals == 2
                and len(filings) == 4 and set(filings.values()) ==
                {("annual_report", annuals[0]), ("annual_report", annuals[1]),
                 ("earnings_call", annuals[1]), ("research_report", annuals[1])})
    if complete and not unclear and (FINANCIAL.search(question) or UNIT.search(question)):
        return HistoricalDecision("unsupported_historical_period", "verified_historical_gap")
    return HistoricalDecision(abstention_reason(index, question, parsed, resolution), "existing")

HEADING_TAGS = ("h2", "h3", "h4", "h5", "h6")
SIDECAR = "_historical_heading_context"
HeadingPairs = tuple[tuple[str, str], ...]
CURRENT = re.compile(r"\b(?:this|current)\s+(?:fiscal\s+|financial\s+|reporting\s+)?(?:year|period)\b", re.I)
AMOUNT_STATEMENT = re.compile(
    r"\b(?:stood at|amounted to|totall?ed|figure|amount|balance|recorded|equalled|(?:was|were)\s+[-(]?\d)\b", re.I,
)


def heading_pairs(soup: BeautifulSoup) -> HeadingPairs:
    """A heading may pass only intervening whitespace and comments to its next paragraph."""
    pairs = []
    for tag in soup.find_all(HEADING_TAGS):
        for sibling in tag.next_siblings:
            if isinstance(sibling, Comment) or isinstance(sibling, NavigableString) and not sibling.strip():
                continue
            if isinstance(sibling, Tag) and sibling.name == "p":
                pairs.append((tag.get_text(" ", strip=True), sibling.get_text(" ", strip=True)))
            break
    return tuple(pairs)


def attach_headings(soup: BeautifulSoup, parents: list[Document]) -> None:
    if parents:
        # Private annotation survives in-process indexing and leaves Document fields
        # and metadata exactly as C+B emitted them.
        setattr(parents[0], SIDECAR, heading_pairs(soup))


def adjacent_evidence(pairs: HeadingPairs, filing_year: int, wanted: int) -> str:
    for title, paragraph in pairs:
        title_financial = bool(FINANCIAL.search(title))
        if GOVERNANCE.search(title) or UNRELATED.search(title) and not title_financial:
            continue
        in_units = bool(UNIT.search(title))
        title_years, title_unresolved = period(title, filing_year)
        previous_period = title_years, title_unresolved
        for offset, sentence in enumerate(SENTENCE.split(paragraph)):
            sentence_years, sentence_unresolved = period(sentence, filing_year)
            if not sentence_years and not sentence_unresolved and CURRENT.search(sentence):
                sentence_years = {filing_year}
            local_financial = bool(FINANCIAL.search(sentence))
            continuation = bool(CONTINUATION.search(sentence))
            if sentence_years or sentence_unresolved:
                dates, unresolved = sentence_years, sentence_unresolved
            else:
                dates, unresolved = previous_period if continuation else (title_years, title_unresolved)
            # Subsequent statements need either a local historical date or an
            # explicit reference to the immediately preceding statement.
            if offset and not continuation and not (wanted in sentence_years and local_financial):
                previous_period = sentence_years, sentence_unresolved
                continue
            previous_period = dates, unresolved
            if wanted not in dates and not unresolved:
                continue
            if UNRELATED.search(sentence) and not local_financial and not CURRENCY.search(sentence):
                continue
            financial_context = title_financial or local_financial or (in_units and AMOUNT_STATEMENT.search(sentence))
            if money(sentence, in_units, bool(financial_context)):
                return title + "\n" + sentence
    return ""


def historical_heading_policy(index: LexicalIndex, question: str, parsed: dict,
                      eligible: set[int] | None, resolution: str) -> HistoricalDecision:
    wanted = explicit_year(question, parsed)
    if wanted is not None and resolution == "resolved" and len(parsed["companies"]) == 1 and parsed["doc_type"] == "annual_report":
        parents = [index.chunks[pos] for pos in sorted(eligible or ())]
        years = [c.metadata["fiscal_year"] for c in parents if c.metadata["doc_type"] == "annual_report"]
        if years and wanted < min(years) - 1:
            for chunk in parents:
                pairs = getattr(chunk, SIDECAR, ())
                if pairs:
                    evidence = adjacent_evidence(pairs, chunk.metadata["fiscal_year"], wanted)
                    if evidence:
                        return HistoricalDecision(None, "adjacent_heading_veto", chunk.metadata["source"], evidence)
    return historical_gap_policy(index, question, parsed, eligible, resolution)

ROLE = (
    r"\b(?:c[efotir]o|chief\s+(?:executive|financial|finance|operating|technology|"
    r"technical|information|risk|legal|accounting|people)\s+officer|"
    r"finance\s+(?:chief|director)|(?:board\s+)?chair(?:man|woman|person)?|"
    r"president|treasurer|director|officer)\b"
)
OFFICER = re.compile(ROLE, re.I)
IDENTITY = re.compile(
    r"^\s*(?:who\b|which\s+(?:person|individual|executive|officer|director)\b|"
    rf"(?:which|name(?:\s+the)?)\s+{ROLE}|"
    r"(?:what|give)\b[^?]*?\b(?:name\s+of|(?:officer|director|cfo|ceo|chair|president)['’]s\s+name)\b)",
    re.I,
)
TIME_REQUEST = re.compile(
    r"^\s*(?:when\b|(?:in |on |at )?(?:what|which)\s+(?:date|year|month|day)\b|"
    r"how\s+(?:long|many\s+(?:days|months|years))\b)", re.I,
)
TENURE_REQUEST = re.compile(
    r"^\s*what\s+(?:is|was|were)\b[^?]*?\b(?:tenure|term in office|years in office|"
    r"appointment date|departure date|start date|succession date|retirement date)\b", re.I,
)
ROLE_EVENT = re.compile(
    r"\b(?:serv\w*|held|hold\w*|tenure|appoint\w*|succeed\w*|replace\w*|"
    r"resign\w*|retir\w*|stepp?\w*\s+down|took office|take office|left office|"
    r"assum\w*\s+office|became|become)\b", re.I,
)
MONETARY_REQUEST = re.compile(
    r"^\s*how much\b|\b(?:salary|compensation|remuneration|pay package|"
    r"severance|payout|appointment bonus|in (?:usd|hkd|eur|gbp)\b)\b", re.I,
)


def officer_intent(question: str) -> bool:
    if not OFFICER.search(question):
        return False
    if IDENTITY.search(question):
        return True
    if MONETARY_REQUEST.search(question):
        return False
    return bool(TENURE_REQUEST.search(question) or TIME_REQUEST.search(question) and ROLE_EVENT.search(question))


def historical_policy(index: LexicalIndex, question: str, parsed: dict,
                      eligible: set[int] | None, resolution: str) -> HistoricalDecision:
    decision = historical_heading_policy(index, question, parsed, eligible, resolution)
    if decision.route == "verified_historical_gap" and officer_intent(question):
        return HistoricalDecision(abstention_reason(index, question, parsed, resolution), "officer_intent_exemption")
    return decision


def retrieve(index: LexicalIndex, question: str) -> list[Document]:
    """Tasks 2 and 3: at most MAX_RETRIEVED of the chunks given to build_index, best first.

    Return [] when the corpus cannot answer the question: the generator then answers NOT_FOUND.
    """
    ### YOUR CODE HERE
    parsed = parse_query(question)
    subjects = parsed["companies"]
    eligible, resolution = company_candidates(index, subjects)
    if historical_policy(index, question, parsed, eligible, resolution).reason is not None:
        return []
    ranking = ranked_positions(index, question)
    if eligible is None:
        return [index.chunks[position] for position in ranking[:MAX_RETRIEVED]]
    eligible_order = [position for position in ranking if position in eligible]
    ranking = eligible_order
    if parsed.get("doc_type") == "annual_report":
        ranking = rank_financial_rows(index, ranking, question)
    if len(subjects) > 1:
        ranking = allocate_comparison(index, ranking)
    parents = [index.chunks[position] for position in ranking[:MAX_RETRIEVED]]
    if not parents or len(subjects) != 1 or not parsed.get("doc_type"):
        return parents
    parents = promote_prose(index, question, parsed, eligible_order, parents)
    return narrow_financial_passage(index, question, parsed, parents)


# =============================================================================
# Provided code below. Do not change it.
# =============================================================================

LLM_MODEL = "deepseek-v4-flash"
DOC_TYPES = ("annual_report", "earnings_call", "research_report")

MAX_CHUNK_CHARS = 1500  # characters per chunk
MAX_RETRIEVED = 5       # chunks per question
TIME_LIMIT_SECONDS = 30 * 60

# USD per 1M tokens, only for the cost estimate that the runner prints.
PRICE_LLM_INPUT, PRICE_LLM_OUTPUT = 0.15, 0.60

# Points (Section 2 of the handout).
POINTS = {"1.1": 8, "1.2": 7, "2.1": 5, "2.2": 10, "2.3": 15, "3": 10, "4": 20}
RECALL_ZERO, RECALL_FULL = 0.50, 0.90  # Task 2.3: 0 points at or below RECALL_ZERO, full points from RECALL_FULL
MAX_LINE_CHARS = 400                   # Task 1.1
MIN_PROBES_FOUND = 0.9                 # Task 1.2


class UsageTracker(BaseCallbackHandler):
    """Counts LLM tokens, for the cost estimate. There is no budget."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.llm_calls = self.llm_input_tokens = self.llm_output_tokens = 0

    def on_llm_end(self, response, **kwargs) -> None:
        tokens_in = tokens_out = 0
        for generations in response.generations:
            for generation in generations:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None) or {}
                tokens_in += usage.get("input_tokens", 0)
                tokens_out += usage.get("output_tokens", 0)
        with self._lock:
            self.llm_calls += 1
            self.llm_input_tokens += tokens_in
            self.llm_output_tokens += tokens_out

    def cost(self) -> float:
        return (self.llm_input_tokens * PRICE_LLM_INPUT + self.llm_output_tokens * PRICE_LLM_OUTPUT) / 1e6

    def summary(self) -> dict:
        return {"llm_calls": self.llm_calls, "llm_input_tokens": self.llm_input_tokens,
                "llm_output_tokens": self.llm_output_tokens, "cost_usd": round(self.cost(), 4)}


USAGE = UsageTracker()            # your calls
GENERATOR_USAGE = UsageTracker()  # the generator's calls


def _chat(usage: UsageTracker, temperature: float, thinking: bool, max_tokens: int | None) -> ChatDeepSeek:
    return ChatDeepSeek(
        model=LLM_MODEL,
        api_key=os.environ["DEEPSEEK_API_KEY"],
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=3,
        # Thinking mode ignores `temperature` and its tokens count as output.
        extra_body={"thinking": {"type": "enabled" if thinking else "disabled"}},
        callbacks=[usage],
    )


def make_llm(temperature: float = 0.0, thinking: bool = False, max_tokens: int | None = None) -> ChatDeepSeek:
    """deepseek-v4-flash. Use it for every LLM call you make (only in parse_query, build_index and retrieve)."""
    return _chat(USAGE, temperature, thinking, max_tokens)


# ----------------------------------------------------------------------------- the generator

GENERATOR_PROMPT = """You answer questions about company reports, using only the context below.

Context:
{context}

Question: {question}

Rules:
- Use only the context. The header of each passage says which document it comes from.
- Check that the passage you use is about the company and the fiscal year that the question asks about.
- If the context does not contain the answer, reply exactly NOT_FOUND.
- For a number, reply with that one number only, in the unit the question asks for, without units, words or other numbers (for example: 1913.4).
- For a name (a person, a company, a city, an audit firm or a rating), reply with the name only.

Answer:"""

_generator: ChatDeepSeek | None = None


def format_context(chunks: list[Document]) -> str:
    """The retrieved chunks as the generator sees them: a header from the metadata, then the text."""
    parts = []
    for i, chunk in enumerate(chunks, 1):
        meta = chunk.metadata or {}
        header = " | ".join(f"{key}: {str(meta[key])[:100]}"
                            for key in ("source", "company", "fiscal_year", "doc_type") if meta.get(key) not in (None, ""))
        parts.append(f"[{i}] {header}\n{chunk.page_content}")
    return "\n\n".join(parts)


def generate(question: str, chunks: list[Document]) -> str:
    """The fixed generator: deepseek-v4-flash answers from the retrieved chunks only."""
    global _generator
    if not chunks:
        return "NOT_FOUND"
    if _generator is None:
        _generator = _chat(GENERATOR_USAGE, 0.0, False, 64)
    prompt = GENERATOR_PROMPT.format(context=format_context(chunks), question=question)
    return str(_generator.invoke(prompt).content).strip()


# ----------------------------------------------------------------------------- loaders

def load_corpus(folder: str | Path) -> dict[str, str]:
    """{file name: raw HTML} for every .html file in the folder."""
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(Path(folder).glob("*.html"))}


def load_json(path: str | Path) -> Any:
    """The parsed file, or None if it does not exist (the private set has no answers)."""
    path = Path(path)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------------------- scoring

# One number: optional minus sign, optional thousands separators, optional decimals.
NUMBER_RE = re.compile(r"(?<![\d.,])-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
TITLES = {"mr", "mrs", "ms", "dr", "prof", "professor", "sir"}
LEGAL_SUFFIXES = {"inc", "corp", "corporation", "ltd", "limited", "plc", "llc", "co"}


def parse_number(text: str) -> float | None:
    """The single number in the text, or None if there is not exactly one."""
    found = NUMBER_RE.findall(text.replace("\u2212", "-"))
    if len(found) != 1:
        return None
    return float(found[0].replace(",", ""))


def normalize(text: str) -> str:
    """Lower case, no punctuation, no titles, padded with spaces for whole-word matching."""
    text = unicodedata.normalize("NFKC", str(text)).lower().replace("_", " ")
    words = [w for w in re.sub(r"[^a-z0-9]+", " ", text).split() if w not in TITLES]
    return " " + " ".join(words) + " "


def company_key(name: Any) -> str:
    """A company name without case, punctuation or legal suffix: 'Northgate Robotics Inc.' -> 'northgate robotics'."""
    return " ".join(w for w in normalize(name).split() if w not in LEGAL_SUFFIXES)


def squash(text: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(text))).strip().casefold()


def as_year(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def answer_correct(answer: str, gold: dict) -> bool:
    answer = str(answer or "")
    said_not_found = " not found " in normalize(answer)
    if gold["type"] == "not_found":
        return said_not_found
    if said_not_found:
        return False
    if gold["type"] == "number":
        value = parse_number(answer)
        if value is None:
            return False
        return abs(value - gold["answer"]) <= max(0.01 * abs(gold["answer"]), 0.05)
    names = [gold["answer"], *gold.get("aliases", [])]
    if not any(normalize(name) in normalize(answer) for name in names):
        return False
    return not any(normalize(other) in normalize(answer) for other in gold.get("reject", []))


def table_score(output: Any, table: dict) -> float:
    """Task 1.1, one table: the share of cells found on a line with their row and column labels and
    without the label of another row, halved if the caption is missing."""
    if not isinstance(output, str) or not table["cells"]:
        return 0.0
    lines = [squash(line) for line in output.splitlines()]
    lines = [line for line in lines if line and len(line) <= MAX_LINE_CHARS]
    labels = {squash(row) for row, _, _ in table["cells"]}

    def kept(row: str, col: str, value: str) -> bool:
        row, col, value = squash(row), squash(col), squash(value)
        others = [o for o in labels if o not in row]  # e.g. "total liabilities" may be in "total liabilities and equity"
        return any(row in line and col in line and value in line and not any(o in line for o in others)
                   for line in lines)

    share = sum(kept(*cell) for cell in table["cells"]) / len(table["cells"])
    return share if squash(table["caption"]) in squash(output) else share / 2


def document_problems(chunks: Any, error: str | None, meta: dict, file_name: str) -> list[str]:
    """Task 1.2, one document: why its chunks fail the checks (an empty list means they pass)."""
    if error:
        return [f"error: {error}"]
    if not isinstance(chunks, list) or not chunks:
        return ["no chunks"]
    if not all(isinstance(c, Document) for c in chunks):
        return ["not a list of Document"]
    problems = []
    longest = max(len(c.page_content) for c in chunks)
    if longest > MAX_CHUNK_CHARS:
        problems.append(f"a chunk has {longest} characters")
    for key, ok in (("source", lambda v: v == file_name),
                    ("company", lambda v: company_key(v) == company_key(meta["company"])),
                    ("fiscal_year", lambda v: as_year(v) == meta["fiscal_year"]),
                    ("doc_type", lambda v: v == meta["doc_type"])):
        wrong = [c.metadata.get(key) for c in chunks if not ok(c.metadata.get(key))]
        if wrong:
            problems.append(f"{key} {wrong[0]!r} (expected {meta.get(key, file_name)!r}) on {len(wrong)} chunk(s)")
    text = squash("\n".join(c.page_content for c in chunks))
    missing = [p for p in meta["probes"] if squash(p) not in text]
    if len(missing) > (1 - MIN_PROBES_FOUND) * len(meta["probes"]):
        problems.append(f"text missing from the chunks: {missing[:3]}")
    return problems


def parse_score(parsed: Any, gold: dict) -> float:
    """Task 2.2, one question: the share of the three fields that are right."""
    if not isinstance(parsed, dict):
        return 0.0
    expected = gold["query"]
    companies = parsed.get("companies")
    if isinstance(companies, str):
        companies = [companies]
    right = 0
    if isinstance(companies, (list, tuple)) and {company_key(c) for c in companies} == {company_key(c) for c in expected["companies"]}:
        right += 1
    if "fiscal_year" in parsed and as_year(parsed["fiscal_year"]) == expected["fiscal_year"] and \
            (parsed["fiscal_year"] is None) == (expected["fiscal_year"] is None):
        right += 1
    if parsed.get("doc_type") == expected["doc_type"]:
        right += 1
    return right / 3


def contains(chunk_text: str, printed: str) -> bool:
    """The fact as printed in the document is in the chunk (a number only as a whole number)."""
    text, printed = squash(chunk_text), squash(printed)
    if re.fullmatch(r"[\d,.%-]+", printed):
        return re.search(rf"(?<![\d.,]){re.escape(printed)}(?![\d]|[.,]\d)", text) is not None
    return printed in text


def retrieval_hit(chunks: list[Document], gold: dict) -> bool:
    """For every fact the question needs, a retrieved chunk of a document that states it contains it."""
    return bool(gold["evidence"]) and all(
        any(c.metadata.get("source") == file and contains(c.page_content, printed)
            for c in chunks for file, printed in group)
        for group in gold["evidence"])


def clip(x: float) -> float:
    return max(0.0, min(1.0, x))


# ----------------------------------------------------------------------------- runner

def main() -> None:
    parser = argparse.ArgumentParser(description="FTEC5660 HW4: retrieval for RAG over company reports")
    parser.add_argument("--data-folder", default="public_test",
                        help="folder with corpus/, questions.json and (optionally) the answer files")
    parser.add_argument("--output", default="results.csv")
    args = parser.parse_args()

    folder = Path(args.data_folder)
    corpus = load_corpus(folder / "corpus")
    questions = load_json(folder / "questions.json")
    ground_truth = load_json(folder / "ground_truth.json")
    docs_meta = load_json(folder / "docs.json")
    tables = load_json(folder / "tables.json")
    print(f"{len(corpus)} documents, {len(questions)} questions")
    start = time.perf_counter()
    points: dict[str, float] = {}

    # Task 1.1: tables (no model calls allowed)
    if tables:
        before = USAGE.llm_calls
        scores = []
        for table in tables:
            try:
                scores.append(table_score(table_to_text(table["html"]), table))
            except Exception as e:
                print(f"table_to_text failed on a table of {table['source']}: {e!r}")
                scores.append(0.0)
        if USAGE.llm_calls != before:
            print("WARNING: table_to_text called the LLM, which is not allowed (Task 1.1 = 0).")
            scores = [0.0]
        points["1.1"] = POINTS["1.1"] * sum(scores) / len(scores)
        print(f"\nTask 1.1 table_to_text: {sum(scores) / len(scores):.1%} of the table cells kept with their labels")

    # Task 1.2: chunks (no model calls allowed)
    before = USAGE.llm_calls
    chunks_by_file: dict[str, list] = {}
    errors: dict[str, str] = {}
    for file_name, html in corpus.items():
        try:
            chunks_by_file[file_name] = list(chunk_document(file_name, html) or [])
        except Exception as e:
            traceback.print_exc()
            chunks_by_file[file_name], errors[file_name] = [], repr(e)
    called_models = USAGE.llm_calls != before
    if called_models:
        print("WARNING: chunk_document called the LLM, which is not allowed (Task 1.2 = 0).")
    if docs_meta:
        problems = {f: document_problems(chunks_by_file.get(f), errors.get(f), m, f) for f, m in docs_meta.items()}
        passed = sum(not p for p in problems.values()) / len(problems)
        points["1.2"] = 0.0 if called_models else POINTS["1.2"] * passed
        print(f"Task 1.2 chunk_document: {passed:.1%} of the documents pass")
        for f, p in [(f, p) for f, p in problems.items() if p][:5]:
            print(f"  {f}: {'; '.join(p)}")

    # the chunks that retrieve() may return
    all_chunks = [c for f in sorted(chunks_by_file) for c in chunks_by_file[f]
                  if isinstance(c, Document) and len(c.page_content) <= MAX_CHUNK_CHARS]
    by_text: dict[str, list[Document]] = {}
    for c in all_chunks:
        by_text.setdefault(c.page_content, []).append(c)
    print(f"{len(all_chunks)} chunks to index")

    # Task 2.2: query parsing
    parsed: dict[str, Any] = {}
    for qid, question in questions.items():
        try:
            parsed[qid] = parse_query(question)
        except Exception as e:
            parsed[qid] = f"error: {e!r}"

    # Tasks 2.1, 2.3 and 3: retrieval
    index = build_index(all_chunks)
    index_seconds = time.perf_counter() - start
    print(f"Index built in {index_seconds:.1f}s | {USAGE.summary()}")
    retrieved: dict[str, list[Document]] = {}
    valid: dict[str, bool] = {}
    for qid, question in questions.items():
        try:
            result = retrieve(index, question)
            ok = isinstance(result, (list, tuple)) and len(result) <= MAX_RETRIEVED
            kept = []
            for chunk in list(result or []) if isinstance(result, (list, tuple)) else []:
                matches = by_text.get(getattr(chunk, "page_content", None), [])
                if not matches:
                    ok = False
                    continue
                source = (getattr(chunk, "metadata", None) or {}).get("source")
                kept.append(next((m for m in matches if m.metadata.get("source") == source), matches[0]))
            retrieved[qid], valid[qid] = kept[:MAX_RETRIEVED], ok
        except Exception:
            traceback.print_exc()
            retrieved[qid], valid[qid] = [], False
    retrieval_seconds = time.perf_counter() - start - index_seconds

    # Task 4: the fixed generator
    def answer(qid: str) -> str:
        try:
            return generate(questions[qid], retrieved[qid])
        except Exception as e:
            print(f"Generator failed on {qid}: {e!r}")
            return ""

    with ThreadPoolExecutor(max_workers=8) as pool:
        answers = dict(zip(questions, pool.map(answer, questions)))
    total_seconds = time.perf_counter() - start

    rows = []
    for qid, question in questions.items():
        sources = sorted({c.metadata.get("source", "") for c in retrieved[qid]})
        row = {"id": qid, "category": "", "question": question, "parsed": json.dumps(parsed[qid], default=str),
               "parse_score": "", "retrieved": ";".join(sources), "valid": valid[qid], "retrieval_hit": "",
               "answer": answers[qid], "correct": "", "expected": ""}
        if ground_truth and qid in ground_truth:
            gold = ground_truth[qid]
            row["category"] = gold["category"]
            row["parse_score"] = round(parse_score(parsed[qid], gold), 3)
            row["retrieval_hit"] = retrieval_hit(retrieved[qid], gold) if gold["evidence"] else ""
            row["correct"] = answer_correct(answers[qid], gold)
            if not row["correct"]:
                row["expected"] = gold["answer"]
        rows.append(row)
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {args.output}")

    if ground_truth:
        graded = [r for r in rows if r["id"] in ground_truth]
        answerable = [r for r in graded if ground_truth[r["id"]]["evidence"]]
        unanswerable = [r for r in graded if not ground_truth[r["id"]]["evidence"]]
        parse_mean = sum(r["parse_score"] for r in graded) / len(graded)
        non_empty = sum(r["valid"] and bool(r["retrieved"]) for r in answerable) / max(len(answerable), 1)
        recall = sum(r["retrieval_hit"] for r in answerable) / max(len(answerable), 1)
        kept = sum(bool(r["retrieved"]) for r in answerable) / max(len(answerable), 1)
        rejected = sum(not r["retrieved"] for r in unanswerable) / max(len(unanswerable), 1)
        accuracy = sum(r["correct"] for r in graded) / len(graded)
        points["2.1"] = POINTS["2.1"] * non_empty
        points["2.2"] = POINTS["2.2"] * parse_mean
        points["2.3"] = POINTS["2.3"] * clip((recall - RECALL_ZERO) / (RECALL_FULL - RECALL_ZERO))
        points["3"] = POINTS["3"] * clip(kept + rejected - 1)
        points["4"] = POINTS["4"] * accuracy
        print(f"Task 2.1 valid, non-empty retrieval on answerable questions: {non_empty:.1%}")
        print(f"Task 2.2 parse_query fields right: {parse_mean:.1%}")
        print(f"Task 2.3 retrieval recall@{MAX_RETRIEVED} on answerable questions: {recall:.1%}")
        print(f"Task 3   answerable questions with chunks: {kept:.1%} | unanswerable questions with []: {rejected:.1%}")
        print(f"Task 4   answer accuracy: {accuracy:.1%}")
        by_category: dict[str, list[tuple]] = {}
        for r in graded:
            by_category.setdefault(r["category"], []).append((r["correct"], r["retrieval_hit"]))
        print("\nBy category       accuracy   recall")
        for category, results in sorted(by_category.items()):
            hits = [h for _, h in results if h != ""]
            recall_text = f"{sum(hits) / len(hits):.1%}" if hits else "-"
            print(f"  {category:<14}{sum(c for c, _ in results) / len(results):>9.1%}{recall_text:>9}")

    if points:
        print("\nEstimated points (the grade uses the private set):")
        for task in POINTS:
            if task in points:
                print(f"  Task {task:<4}{points[task]:6.2f} / {POINTS[task]}")
        print(f"  Total    {sum(points.values()):6.2f} / {sum(POINTS[t] for t in points)}")

    print(f"\nYour usage: {USAGE.summary()}")
    print(f"Generator usage: {GENERATOR_USAGE.summary()}")
    print(f"Time: {total_seconds:.1f}s (index {index_seconds:.1f}s, retrieval {retrieval_seconds:.1f}s)")
    if total_seconds > TIME_LIMIT_SECONDS:
        print(f"WARNING: the run took longer than the {TIME_LIMIT_SECONDS // 60}-minute limit.")


if __name__ == "__main__":
    main()
