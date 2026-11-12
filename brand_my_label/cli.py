"""brand-my-label LABEL.pdf LOGO.png [-o OUT.pdf] [--keep-size]"""

import argparse
import sys
from pathlib import Path

from .stamp import StampError, stamp_pdf


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="brand-my-label",
                                description="Stamp your logo on a shipping label PDF.")
    p.add_argument("label", type=Path)
    p.add_argument("logo", type=Path)
    p.add_argument("-o", "--out", type=Path)
    p.add_argument("--keep-size", action="store_true",
                   help="do not re-centre small pages (A6...) on A4")
    a = p.parse_args(argv)
    out = a.out or a.label.with_name(a.label.stem + "-branded.pdf")
    try:
        r = stamp_pdf(a.label.read_bytes(), a.logo.read_bytes(), to_a4=not a.keep_size)
    except StampError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    out.write_bytes(r.pdf)
    print(f"{out}  mode={r.mode} carrier={r.carrier} a4={r.normalized_a4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
