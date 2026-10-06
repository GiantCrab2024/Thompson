"""Command line for the flagging module.

  python3 -m flagging gate2 EXPORT [--samples SAMPLES.csv] [--out gate2.csv]
  python3 -m flagging run EXPORT --outputs OUTPUTS.jsonl --model MODEL [--samples SAMPLES.csv] [--out-dir DIR]
  python3 -m flagging consistency EXPORT --outputs FIVE.jsonl --model MODEL [--out-dir DIR]

EXPORT is a MODES XML or CSV export. See pipeline.py for the OUTPUTS format.
"""

import argparse
import datetime
import json
import os
import sys

from . import consistency, sheets
from .gate2 import ELEMENT_ORDER, score_record
from .llm import CountingClient, ModelError, OpenAIChatClient
from .modes import load_export
from .pipeline import load_outputs, load_samples, rows_to_json, score_batch, select_records


def _selected(args):
    records = load_export(args.export)
    samples = load_samples(args.samples) if args.samples else None
    return select_records(records, samples)


def _client(args):
    return CountingClient(OpenAIChatClient(model=args.model, temperature=args.temperature, env_file=args.env_file))


def cmd_gate2(args):
    selected = _selected(args)
    columns = ["MODES no.", "Sample", "Detail", "Gate 2", "Elements"] + ELEMENT_ORDER + ["Notes"]
    rows = []
    for record, sample in selected:
        r = score_record(record)
        row = {"MODES no.": record.number, "Sample": sample, "Detail": r.detail_score,
               "Gate 2": r.decision, "Elements": r.element_count, "Notes": "; ".join(r.notes)}
        row.update({e: "yes" if r.elements[e] else "" for e in ELEMENT_ORDER})
        rows.append(row)
        print("%-20s Detail %d  %-4s  %s" % (record.number, r.detail_score, r.decision, "; ".join(r.notes)))
    if args.out:
        sheets.write_csv(args.out, columns, rows)
        print("wrote", args.out)


def cmd_run(args):
    selected = _selected(args)
    outputs = load_outputs(args.outputs)
    client = _client(args)
    rows = score_batch(client, selected, outputs, log=lambda m: print(m, file=sys.stderr))
    os.makedirs(args.out_dir, exist_ok=True)
    date = datetime.date.today().isoformat()
    sheets.write_b2(os.path.join(args.out_dir, "sheet_B2_records.csv"), rows)
    results = [r for row in rows for r in (row.gate3_a, row.gate3_b) if r is not None]
    sheets.write_b3(os.path.join(args.out_dir, "sheet_B3_claims.csv"), results, date=date)
    with open(os.path.join(args.out_dir, "flagging_results.json"), "w", encoding="utf-8") as f:
        json.dump(rows_to_json(rows), f, indent=2, ensure_ascii=False)
    print("scored %d records, %d outputs, %d model calls; wrote %s" % (len(rows), len(results), client.calls, args.out_dir))


def cmd_consistency(args):
    by_number = {r.number: r for r in load_export(args.export)}
    outputs = load_outputs(args.outputs)
    client = _client(args)
    comparisons = []
    for o in outputs:
        if o["record"] not in by_number:
            sys.exit("record %s is not in the export" % o["record"])
        comparisons.append(consistency.compare_output(client, by_number[o["record"]], o))
    os.makedirs(args.out_dir, exist_ok=True)
    sheets.write_csv(os.path.join(args.out_dir, "consistency_claims.csv"),
                     consistency.CLAIM_COLUMNS, consistency.claim_rows(comparisons))
    sheets.write_csv(os.path.join(args.out_dir, "consistency_outputs.csv"),
                     consistency.OUTPUT_COLUMNS, consistency.output_rows(comparisons))
    text = consistency.summary(comparisons)
    with open(os.path.join(args.out_dir, "consistency_summary.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print("\n%d model calls; wrote %s" % (client.calls, args.out_dir))


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m flagging")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp, model):
        sp.add_argument("export", help="MODES export (.xml or .csv)")
        sp.add_argument("--samples", help="CSV with 'MODES no.' and 'Sample' columns, in B2 order")
        if model:
            sp.add_argument("--outputs", required=True, help="JSON Lines file of generated outputs")
            sp.add_argument("--model", required=True, help="model name for both Gate 3 calls")
            sp.add_argument("--temperature", type=float, default=0.0)
            sp.add_argument("--env-file", help=".env file holding OPENAI_API_KEY and OPENAI_API_URL")
            sp.add_argument("--out-dir", default="flagging_out")

    g2 = sub.add_parser("gate2", help="score records for Gate 2 (no model calls)")
    common(g2, model=False)
    g2.add_argument("--out", help="write a CSV of scores")
    g2.set_defaults(func=cmd_gate2)

    run = sub.add_parser("run", help="gates 2 and 3 over a batch; writes Sheets B2 and B3")
    common(run, model=True)
    run.set_defaults(func=cmd_run)

    con = sub.add_parser("consistency", help="run Gate 3 twice on the same outputs and compare")
    common(con, model=True)
    con.set_defaults(func=cmd_consistency)

    args = p.parse_args(argv)
    try:
        args.func(args)
    except ModelError as e:
        sys.exit("error: %s" % e)


if __name__ == "__main__":
    main()
