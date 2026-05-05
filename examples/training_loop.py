from __future__ import annotations

import argparse
import time

from cllg import cllg, output, progress


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Show progress from deep training code."
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--epochs", type=_positive_int, default=4)
    parser.add_argument("--delay", type=_non_negative_float, default=0.05)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with cllg():
        final_loss = train_model(epochs=args.epochs, delay=args.delay)
        output(
            human=f"training complete loss={final_loss:.3f}",
            agent={"ok": True, "epochs": args.epochs, "loss": final_loss},
        )
    return 0


def train_model(*, epochs: int, delay: float) -> float:
    loss = 1.0
    with progress("training", total=epochs) as task:
        task.message(
            human="initialized training loop",
            agent={"event": "training_initialized", "epochs": epochs},
        )
        for epoch in range(1, epochs + 1):
            loss = train_epoch(epoch=epoch, loss=loss, delay=delay)
            task.update(
                human=f"epoch {epoch}/{epochs} loss={loss:.3f}",
                agent={
                    "event": "epoch",
                    "epoch": epoch,
                    "epochs": epochs,
                    "loss": loss,
                },
            )
    return loss


def train_epoch(*, epoch: int, loss: float, delay: float) -> float:
    time.sleep(delay)
    return round(loss * 0.72 + (epoch * 0.01), 6)


def _positive_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _non_negative_float(raw_value: str) -> float:
    value = float(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
