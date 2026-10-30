"""Generate a simple synthetic demo GIF storyboard (no screen recording required)."""

from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install pillow: pip install pillow") from exc

FRAMES = [
    "1. Submit synthetic\ninspection event",
    "2. LangGraph investigates\nSQL history + SOP RAG",
    "3. Deterministic route:\naction_required",
    "4. Human reviews draft\nin Streamlit inbox",
    "5. Approve resume →\nexactly one SQL ticket",
]


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "docs" / "demo.gif"
    out.parent.mkdir(parents=True, exist_ok=True)
    images = []
    for text in FRAMES:
        img = Image.new("RGB", (720, 405), color=(18, 32, 47))
        draw = ImageDraw.Draw(img)
        draw.rectangle((20, 20, 700, 385), outline=(90, 180, 200), width=3)
        draw.text((40, 40), "PaintOps — SYNTHETIC DEMO", fill=(90, 180, 200))
        draw.text((40, 150), text, fill=(240, 244, 248))
        draw.text(
            (40, 340),
            "Not for production industrial decisions",
            fill=(180, 160, 120),
        )
        images.append(img)
    images[0].save(
        out,
        save_all=True,
        append_images=images[1:],
        duration=900,
        loop=0,
    )
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
