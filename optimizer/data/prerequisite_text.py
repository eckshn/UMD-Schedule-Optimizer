"""
Turn UMD prerequisite sentences (Testudo's "Prerequisite: ..." text) into the
prerequisite trees ``DataLoader`` reads.

    "MATH246 or ENES221; and (CMSC131, ENME202, ENAE202 or ENEE150)."
    -> {"type": "and", "conditions": [
           {"type": "or", "courses": ["MATH246", "ENES221"]},
           {"type": "or", "courses": ["CMSC131", "ENME202", "ENAE202", "ENEE150"]}]}

Reading rules, from the phrasing Testudo uses:

- ``;`` and ``.`` separate clauses. Clauses joined by "; or" are
  alternatives; the rest must all hold ("; and", or no connective).
- Within a clause, ``and`` binds more loosely than ``or``: "A, B, and either
  C or (D and E)" is A and B and (C or (D and E)). Commas follow the
  connective around them: "A, B, or C" is an OR, "A, B, and C" an AND.
- "1 course ... from (...)" and "one of (the following ...)" make the list
  that follows an OR, even with only commas.
- Parentheses group.
- Alternatives that name no course ("or permission of instructor", "or
  equivalent", "or a score of 5 on the ... AP exam") are dropped, so the
  courses stay required; text with no course codes means no prerequisite.
- Corequisite wording inside a prerequisite ("must have completed or be
  concurrently enrolled in X") counts X as a prerequisite.
- Minimum grades aren't kept (the planner treats completed courses as an A).
"""

import re
from typing import Dict, List, Optional, Union

_TOKEN = re.compile(
    r"(?P<code>\b[A-Z]{4}\s?\d{3}[A-Z]?\b)"
    r"|(?P<any>\b(?:1|one)\s+course\b[^;().]*?\bfrom\b|\bone\s+of\b|\bfrom\b(?=\s*\())"
    r"|(?P<word>\b(?:and|or)\b)"
    r"|(?P<punct>[;,()]|\.(?=\s|$))",
    re.IGNORECASE,
)

Token = Union[str, list]
Node = Optional[Dict]
ANY = "ANY"


def parse_prerequisite_text(text: str) -> Node:
    """The prerequisite tree for ``text``, or None if it names no course."""
    tokens: List[str] = []
    for match in _TOKEN.finditer(text or ""):
        if match.group("code"):
            tokens.append(match.group("code").replace(" ", "").upper())
        elif match.group("any"):
            tokens.append(ANY)
        elif match.group("word"):
            tokens.append(match.group("word").lower())
        else:
            tokens.append(";" if match.group("punct") == "." else match.group("punct"))
    return _to_json(_clauses(_nest(tokens)))


def _nest(tokens: List[str]) -> List[Token]:
    """Group parenthesized tokens into nested lists (unbalanced parentheses are tolerated)."""
    stack: List[List[Token]] = [[]]
    for token in tokens:
        if token == "(":
            stack.append([])
        elif token == ")":
            if len(stack) > 1:
                inner = stack.pop()
                stack[-1].append(inner)
        else:
            stack[-1].append(token)
    while len(stack) > 1:
        inner = stack.pop()
        stack[-1].append(inner)
    return stack[0]


def _split(tokens: List[Token], separators: set) -> List[List[Token]]:
    parts: List[List[Token]] = [[]]
    for token in tokens:
        if isinstance(token, str) and token in separators:
            parts.append([])
        else:
            parts[-1].append(token)
    return parts


def _clauses(tokens: List[Token]) -> Node:
    """Clauses split by ";": "; or" joins alternatives, anything else joins requirements."""
    alternatives: List[List[List[Token]]] = [[]]
    for clause in _split(tokens, {";"}):
        if clause and clause[0] == "or":
            alternatives.append([])
        if clause and clause[0] in ("and", "or"):
            clause = clause[1:]
        alternatives[-1].append(clause)
    return _combine("or", [_combine("and", [_clause(c) for c in group]) for group in alternatives])


def _clause(tokens: List[Token], any_of: bool = False) -> Node:
    """One clause: ``and`` binds more loosely than ``or``; commas follow the connective."""
    if ";" in [t for t in tokens if isinstance(t, str)]:
        return _clauses(tokens)
    has_and = "and" in tokens
    if any_of and not has_and:
        return _combine("or", [_operand(p) for p in _split(tokens, {",", "or"})])
    parts = _split(tokens, {"and"}) if has_and else [tokens]
    nodes = []
    for part in parts:
        if part and part[0] == ANY:
            rest = part[1:]
            if len(rest) == 1 and isinstance(rest[0], list):  # "1 course from (A, B)"
                nodes.append(_clause(rest[0], any_of=True))
            else:                                              # "one of the following: A, B"
                nodes.append(_combine("or", [_operand(p) for p in _split(rest, {",", "or"})]))
        elif "or" in part:
            nodes.append(_combine("or", [_operand(p) for p in _split(part, {",", "or"})]))
        else:
            nodes.append(_combine("and", [_operand(p) for p in _split(part, {","})]))
    return _combine("and", nodes)


def _operand(tokens: List[Token]) -> Node:
    """Courses and groups between separators; an ANY marker makes the following group an OR."""
    nodes = []
    any_of = False
    for token in tokens:
        if token == ANY:
            any_of = True
        elif isinstance(token, list):
            nodes.append(_clause(token, any_of=any_of))
            any_of = False
        elif token not in ("and", "or", ",", ";"):
            nodes.append({"type": "course", "code": token})
    return _combine("and", nodes)


def _combine(kind: str, nodes: List[Node]) -> Node:
    """An AND/OR of ``nodes``, dropping empty ones and flattening nested nodes of the same kind."""
    flat: List[Dict] = []
    for node in nodes:
        if node is None:
            continue
        if node["type"] == kind:
            flat.extend(node["items"])
        elif node not in flat:
            flat.append(node)
    if not flat:
        return None
    if len(flat) == 1:
        return flat[0]
    return {"type": kind, "items": flat}


def _to_json(node: Node) -> Node:
    """Convert to the loader's format: course / or (courses + conditions) / and (conditions)."""
    if node is None:
        return None
    if node["type"] == "course":
        return {"type": "course", "courses": [node["code"]]}
    if node["type"] == "and":
        return {"type": "and", "conditions": [_to_json(n) for n in node["items"]]}
    courses = [n["code"] for n in node["items"] if n["type"] == "course"]
    conditions = [_to_json(n) for n in node["items"] if n["type"] != "course"]
    result: Dict = {"type": "or", "courses": list(dict.fromkeys(courses))}
    if conditions:
        result["conditions"] = conditions
    return result
