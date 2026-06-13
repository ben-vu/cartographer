"""End-to-end pipeline runner.

    python run_pipeline.py            # run everything
    python run_pipeline.py --from rfm # resume from a stage
    python run_pipeline.py --only model
    python run_pipeline.py --no-generate   # skip synthetic data (use real CSVs)

Stages, in order:
    generate -> load -> clean -> rfm -> model -> export
"""
from __future__ import annotations

import argparse
import logging
import time

from src import (
    clean_data,
    export_for_tableau,
    generate_sample_data,
    load_to_postgres,
    reorder_model,
    rfm_segmentation,
)
from src import db

STAGES = ["generate", "load", "clean", "rfm", "model", "export"]


def _run_stage(name: str) -> None:
    log = logging.getLogger("pipeline")
    t0 = time.time()
    log.info("=" * 70)
    log.info("STAGE: %s", name.upper())
    log.info("=" * 70)
    if name == "generate":
        generate_sample_data.generate()
    elif name == "load":
        load_to_postgres.load()
    elif name == "clean":
        clean_data.clean()
    elif name == "rfm":
        rfm_segmentation.run()
    elif name == "model":
        reorder_model.run()
    elif name == "export":
        export_for_tableau.export()
    log.info("Stage '%s' finished in %.1fs", name, time.time() - t0)


def main() -> None:
    ap = argparse.ArgumentParser(description="Instacart RFM + reorder pipeline")
    ap.add_argument("--from", dest="from_stage", choices=STAGES,
                    help="resume from this stage onward")
    ap.add_argument("--only", choices=STAGES, help="run a single stage")
    ap.add_argument("--no-generate", action="store_true",
                    help="skip synthetic generation (bring your own CSVs)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("pipeline")

    stages = STAGES[:]
    if args.only:
        stages = [args.only]
    elif args.from_stage:
        stages = STAGES[STAGES.index(args.from_stage):]
    if args.no_generate and "generate" in stages:
        stages.remove("generate")

    # Stages after 'generate' need the database.
    if any(s != "generate" for s in stages) and not db.ping():
        raise SystemExit(
            "PostgreSQL not reachable. Start it and check .env, then retry."
        )

    t0 = time.time()
    for s in stages:
        _run_stage(s)
    log.info("\nPIPELINE COMPLETE in %.1fs. Tableau extracts in outputs/tableau/.",
             time.time() - t0)


if __name__ == "__main__":
    main()
