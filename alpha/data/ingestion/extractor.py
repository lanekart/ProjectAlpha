import zipfile
from pathlib import Path

from alpha.config import settings


class ArchiveExtractor:
    """
    Responsible only for extracting NSE bhavcopy ZIP files.
    """

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or settings.extracted_data_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def extract(self, zip_path: str | Path) -> Path:
        """
        Extract a bhavcopy ZIP archive and return extracted CSV path.
        """

        zip_path = Path(zip_path)

        if not zip_path.exists():
            raise FileNotFoundError(f"ZIP file not found: {zip_path}")

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(self.output_dir)
            extracted_files = zip_ref.namelist()

        if not extracted_files:
            raise ValueError("No files found inside ZIP")

        return self.output_dir / extracted_files[0]
