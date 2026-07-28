from __future__ import annotations

import argparse
import json
from pathlib import Path

from god_bot.filters import prepare_corpus_message


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert RealPersonaChat JSON files to God TSV."
    )
    parser.add_argument(
        "dialogues",
        type=Path,
        help="Path to real_persona_chat/dialogues",
    )
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--max-utterance-length",
        type=int,
        default=20,
        help="Exclude utterances longer than this (default: 20)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    files = sorted(args.dialogues.glob("*.json"))
    if not files:
        raise SystemExit(f"No dialogue JSON files found in {args.dialogues}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    count = 0
    with temporary.open("w", encoding="utf-8") as output:
        output.write(
            "# Derived from RealPersonaChat, CC BY-SA 4.0.\n"
            "# Format: dialogue_id<TAB>utterance\n"
        )
        for path in files:
            data = json.loads(path.read_text(encoding="utf-8"))
            dialogue_id = int(data["dialogue_id"])
            for utterance in data["utterances"]:
                text = prepare_corpus_message(
                    str(utterance["text"]),
                    max_length=args.max_utterance_length,
                )
                if text is None:
                    continue
                output.write(f"{dialogue_id}\t{text}\n")
                count += 1
    temporary.replace(args.output)
    print(
        f"Wrote {count} utterances (max {args.max_utterance_length} chars) "
        f"to {args.output}"
    )


if __name__ == "__main__":
    main()
