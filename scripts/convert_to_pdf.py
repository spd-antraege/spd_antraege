"""Convert Antrag markdown files directly to PDF in KDV format."""
import re
from pathlib import Path
from fpdf import FPDF


class AntragPDF(FPDF):
    def __init__(self):
        super().__init__("P", "mm", "A4")
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        self.set_font("Helvetica", "", 9)
        self.cell(0, 5, "Anträge · KDV am 18.04.2026", ln=True)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.line(70, self.get_y() - 2, 140, self.get_y() - 2)
        self.set_font("Helvetica", "", 9)
        self.cell(0, 10, str(self.page_no()), align="C")


def clean_markdown(text):
    """Remove markdown formatting for plain text output."""
    text = text.replace("\\*", "★")  # preserve gendering
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)  # bold markers (handled separately)
    text = text.replace("★", "*")  # restore gendering
    return text


def write_mixed(pdf, text, font_size=10):
    """Write text with **bold** segments and gendering."""
    text = text.replace("\\*", "★")
    parts = re.split(r"(\*\*.*?\*\*)", text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            content = part[2:-2].replace("★", "*")
            pdf.set_font("Helvetica", "B", font_size)
            pdf.write(5, content)
            pdf.set_font("Helvetica", "", font_size)
        else:
            content = part.replace("★", "*")
            pdf.write(5, content)


def md_to_pdf(md_path: Path, out_path: Path):
    """Convert a single markdown Antrag to PDF."""
    text = md_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    pdf = AntragPDF()
    pdf.add_page()
    pdf.set_margins(25, 25, 25)

    # Extract title
    title = ""
    for line in lines:
        if line.strip().startswith("# "):
            title = line.strip()[2:]
            break

    # Title — bold
    pdf.set_font("Helvetica", "B", 11)
    pdf.multi_cell(0, 6, title)
    pdf.ln(2)

    # KDV intro — italic
    pdf.set_font("Helvetica", "I", 10)
    pdf.cell(0, 5, "Die Kreisdelegiertenversammlung wolle beschließen:", ln=True)
    pdf.ln(1)

    # Process body
    skip_title = True
    found_adressat = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue

        # Skip markdown title
        if stripped.startswith("# ") and skip_title:
            skip_title = False
            continue

        # Skip ## headings — handle Begründung specially
        if stripped == "## Begründung":
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 5, "Begründung:", ln=True)
            pdf.set_font("Helvetica", "", 10)
            pdf.ln(1)
            continue

        if stripped.startswith("## "):
            continue

        # Adressat line
        if not found_adressat and ("mögen beschließen" in stripped or "möge beschließen" in stripped):
            clean = stripped.replace("**", "")
            pdf.set_font("Helvetica", "I", 10)
            pdf.multi_cell(0, 5, clean)
            pdf.set_font("Helvetica", "", 10)
            pdf.ln(3)
            found_adressat = True
            continue

        # Numbered list
        if re.match(r"^\d+\.\s", stripped):
            pdf.set_font("Helvetica", "", 10)
            # Handle gendering
            clean = stripped.replace("\\*", "*")
            pdf.multi_cell(0, 5, clean)
            pdf.ln(2)
            continue

        # Bullet list
        if stripped.startswith("- "):
            content = stripped[2:].replace("\\*", "*")
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(5)
            pdf.multi_cell(0, 5, "•  " + content)
            pdf.ln(1)
            continue

        # Table rows — skip
        if stripped.startswith("|"):
            continue

        # Regular paragraph
        pdf.set_font("Helvetica", "", 10)
        clean = stripped.replace("\\*", "*")
        pdf.multi_cell(0, 5, clean)
        pdf.ln(2)

    pdf.output(str(out_path))


def main():
    import sys
    if len(sys.argv) > 1:
        base = Path(sys.argv[1])
    else:
        base = Path.cwd()

    # Look for md/ subdirectory first, fall back to base
    md_dir = base / "md" if (base / "md").is_dir() else base
    pdf_dir = base / "pdf"
    pdf_dir.mkdir(exist_ok=True)

    md_files = sorted(
        f for f in md_dir.glob("*.md")
        if "INTERN" not in f.name
    )

    print(f"Converting {len(md_files)} Anträge to PDF:\n")
    for md in md_files:
        out = pdf_dir / md.name.replace(".md", ".pdf")
        md_to_pdf(md, out)
        size_kb = out.stat().st_size // 1024
        print(f"  {out.name} ({size_kb}KB)")

    print(f"\nDone. {len(md_files)} PDFs written to pdf/")


if __name__ == "__main__":
    main()
