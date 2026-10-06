"""Score a batch of records and outputs through gates 2 and 3.

Generated outputs arrive as JSON Lines, one per output, written by the
generation step:

  {"record": "BEXMS:1999.12", "run": "B", "text": "This is ...",
   "passages": [{"source_id": "S03", "text": "..."}]}

"passages" must be the passages actually retrieved for that generation, so
Gate 3 checks the output against the evidence the model was given.
"""

import json
from dataclasses import asdict, dataclass

from . import flag
from .gate2 import Gate2Result, score_record
from .gate3 import Gate3Result, Passage, run_gate3
from .modes import Record


@dataclass
class RecordRow:
    index: int
    record: Record
    sample: str
    gate2: Gate2Result
    gate3_a: Gate3Result = None
    gate3_b: Gate3Result = None
    flag: str = ""


def output_id(record_number: str, run: str) -> str:
    return "%s-%s" % (record_number, run.upper())


def load_outputs(path: str) -> list:
    outputs = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            run = str(item["run"]).upper()
            if run not in ("A", "B"):
                raise ValueError("line %d: run must be A or B, got %r" % (line_no, item["run"]))
            item["run"] = run
            item["passages"] = [Passage(p["source_id"], p["text"]) for p in item.get("passages", [])]
            outputs.append(item)
    return outputs


def load_samples(path: str) -> list:
    """CSV with columns 'MODES no.' and 'Sample' (R / T / N / S), in B2 order."""
    import csv
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [(r["MODES no."].strip(), r.get("Sample", "").strip()) for r in csv.DictReader(f)]


def select_records(records: list, samples: list = None) -> list:
    """Return [(record, sample_code)] in B2 order."""
    if samples is None:
        return [(r, "") for r in records]
    by_number = {r.number: r for r in records}
    counts = {}
    for r in records:
        counts[r.number] = counts.get(r.number, 0) + 1
    ambiguous = [n for n, _ in samples if counts.get(n, 0) > 1]
    if ambiguous:
        raise ValueError("record numbers used by more than one record in the export: %s" % ", ".join(ambiguous))
    missing = [n for n, _ in samples if n not in by_number]
    if missing:
        raise ValueError("records in the sample list but not in the export: %s" % ", ".join(missing))
    return [(by_number[n], code) for n, code in samples]


def score_batch(client, selected: list, outputs: list, log=print) -> list:
    """Run Gate 2 on every record and Gate 3 on every supplied output."""
    by_key = {}
    for o in outputs:
        key = (o["record"], o["run"])
        if key in by_key:
            raise ValueError("two outputs for record %s run %s" % key)
        by_key[key] = o

    rows = []
    for i, (record, sample) in enumerate(selected, start=1):
        row = RecordRow(index=i, record=record, sample=sample, gate2=score_record(record))
        for run in ("A", "B"):
            o = by_key.get((record.number, run))
            if o is None:
                continue
            if run == "B" and row.gate2.decision == "Stop":
                log("warning: %s was stopped at Gate 2 but has a Run B output; ignoring it" % record.number)
                continue
            res = run_gate3(client, record, o["text"], o["passages"], output_id(record.number, run), run)
            if res.error:
                log("tool fault on %s: %s" % (res.output_id, res.error))
            setattr(row, "gate3_" + run.lower(), res)
        row.flag = flag.combine(row.gate2.detail_score, row.gate3_b.cr_score if row.gate3_b else None)
        rows.append(row)
    return rows


def rows_to_json(rows: list) -> list:
    """Everything stored per record (spec, 'Output requirements')."""
    out = []
    for r in rows:
        out.append({
            "no": r.index,
            "modes_no": r.record.number,
            "sample": r.sample,
            "gate2": asdict(r.gate2),
            "gate3_a": asdict(r.gate3_a) if r.gate3_a else None,
            "gate3_b": asdict(r.gate3_b) if r.gate3_b else None,
            "flag": r.flag,
        })
    return out
