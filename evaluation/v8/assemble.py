"""Reproduce the self-contained integration from the three frozen research files."""
import argparse
from hashlib import sha256
from pathlib import Path
import re
import subprocess
import sys

BASELINE = "6d008816f7efa605c7b2f1a4b0553628e4a51986"
BASELINE_SHA = "6e65ab615bfece13e6717b4171148f188a6ae042bbf714e49d670f6dcafa0379"
MARKER = "# Provided code below. Do not change it."
FROZEN = {
    "veto.py": "038b8da5d56c4a67a34dd9904ed0d38b40ef85b482502a839e2fb96c9bf57c47",
    "evidence_headings.py": "5ad72c03e981d53bb16b5373009662ab455635c5caab1bfcd52429ea8f340e02",
    "officer_policy.py": "e812665697f4da153f2523c3e4be55a25aee022ecc95605600f17ae78ab2a891",
}


def checked(raw: bytes, digest: str, name: str) -> str:
    if sha256(raw).hexdigest() != digest:
        raise ValueError(f"Unexpected source hash for {name}")
    return raw.decode()


def replace(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"Ambiguous assembly seam {old!r}")
    return source.replace(old, new)


def assembled(research: Path) -> str:
    baseline = checked(subprocess.check_output(["git", "show", f"{BASELINE}:hw4.py"]),
                       BASELINE_SHA, "C+B")
    paths = (research.parent.parent / "veto.py", research.parent / "evidence_headings.py",
             research / "officer_policy.py")
    veto, headings, officer = [checked(path.read_bytes(), FROZEN[path.name], path.name) for path in paths]

    gap = veto[veto.index("CHUNK_OVERLAP ="):]
    gap = re.sub(r"(?<!\.)\bYEAR\b", "HISTORICAL_YEAR", gap)
    gap = replace(gap, "def historical_policy(", "def historical_gap_policy(")
    heading = headings[headings.index("HEADING_TAGS ="):]
    heading = replace(heading, "def historical_policy(", "def historical_heading_policy(")
    heading = replace(heading, "return earlier_policy(", "return historical_gap_policy(")
    intent = officer[officer.index("ROLE ="):]
    intent = replace(intent, "decision = heading_policy(", "decision = historical_heading_policy(")

    source = replace(baseline, "from collections.abc import Iterator",
                     "from collections import defaultdict\nfrom collections.abc import Iterator")
    source = replace(source, "from bs4 import BeautifulSoup, Tag",
                     "from bs4 import BeautifulSoup, Comment, NavigableString, Tag")
    policies = "\n\n".join(part.rstrip().replace("hw4.", "") for part in (gap, heading, intent))
    source = replace(source, "\n\ndef retrieve(", "\n\n" + policies + "\n\n\ndef retrieve(")
    source = replace(source, "    return parents + children\n",
                     "    attach_headings(soup, parents)\n    return parents + children\n")
    source = replace(source, "    if abstention_reason(index, question, parsed, resolution) is not None:",
                     "    if historical_policy(index, question, parsed, eligible, resolution).reason is not None:")
    if source.split(MARKER, 1)[1] != baseline.split(MARKER, 1)[1]:
        raise ValueError("Protected lecturer suffix changed")
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("research", type=Path, help="approved officer-intent research directory")
    args = parser.parse_args()
    sys.stdout.write(assembled(args.research.resolve()))


if __name__ == "__main__":
    main()
