"""流水线编排与研判门禁。"""

from pathlib import Path


class Pipeline:
    """管理 run_id 目录与各阶段产物路径。"""

    def __init__(self, project_root: Path, run_id: str) -> None:
        self.project_root = project_root
        self.run_id = run_id
        self.run_dir = project_root / "data" / "runs" / run_id
        self.config_dir = project_root / "config"

    def ensure_run_dir(self) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        return self.run_dir

    def manifest_path(self) -> Path:
        return self.run_dir / "manifest.json"

    def pdf_path(self) -> Path:
        return self.run_dir / "source.pdf"

    def analysis_path(self) -> Path:
        return self.project_root / "analysis" / self.run_id / "analysis.json"

    def check_analysis_gate(self) -> bool:
        """第 ④ 步门禁：analysis.json 须存在。"""
        return self.analysis_path().is_file()

    def require_manifest(self) -> Path:
        path = self.manifest_path()
        if not path.is_file():
            raise FileNotFoundError(
                f"缺少 manifest.json，请先运行 ingest: {path}"
            )
        return path

    def require_pdf(self) -> Path:
        path = self.pdf_path()
        if not path.is_file():
            raise FileNotFoundError(
                f"缺少归档 PDF source.pdf，请先运行 ingest: {path}"
            )
        return path
