from typing import Any
import subprocess
import csv

from structlog import get_logger


from sqc.repository import InternalError
from sqc.validation.io import get_pdb_id, split_models
from sqc.validation.model import (
    Model,
    Residue,
    Result,
    Status,
    WorstClash,
)

logger = get_logger()


class ValidationError(Exception):
    def __init__(self, *args) -> None:
        super().__init__(*args)


class MolProbity:
    def __init__(self, timeout=600) -> None:
        self.timeout = timeout

    def _residue_analysis_output(self, path: str) -> str:
        try:
            proc = subprocess.run(
                ["residue-analysis", path], capture_output=True, timeout=self.timeout
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "Failed to run molprobity residue-analysis in time",
                timeout=self.timeout,
            )
            raise ValidationError("Failed to run residue analysis in time")

        if proc.returncode != 0:
            logger.error(
                "residue-analysis exited with non-zero code", stderr=proc.stderr
            )
            raise InternalError()

        return proc.stdout.decode(encoding="utf-8")

    @staticmethod
    def _nullify_row(row: dict[str, Any]) -> None:
        """Changes dict values from empty strings to None"""
        for key, val in row.items():
            if val == "":
                row[key] = None

    def _get_analysis_dict(self, path: str) -> dict[str, Any]:
        output = self._residue_analysis_output(path).splitlines()
        reader = csv.DictReader(output, dialect="unix")

        per_residue_analysis: dict[str, Any] = {}
        for residue_row in reader:
            residue = residue_row.pop("residue")
            self._nullify_row(residue_row)
            per_residue_analysis[residue] = residue_row

        return per_residue_analysis

    @staticmethod
    def _parse_residue(residue: str) -> Residue:
        split = residue.split()
        chain = split[0]
        number = int(split[1])
        type = split[2]
        return Residue(number=number, chain=chain, residue_type=type)

    def residue_analysis(self, path: str) -> list[Residue] | None:
        logger.debug("Running residue-analysis", path=path)
        all_analysis = self._get_analysis_dict(path)
        residues = []

        for residue_id, analysis in all_analysis.items():
            residue = self._parse_residue(residue_id)

            if analysis["worst_clash"] is not None:
                magnitude = float(analysis["worst_clash"])
                atom = analysis["src_atom"]
                other_atom = analysis["dst_atom"]
                dst_residue = self._parse_residue(analysis["dst_residue"])

                residue.worst_clash = WorstClash(
                    magnitude=magnitude,
                    atom=atom,
                    other_atom=other_atom,
                    other_residue=dst_residue,
                )

            residues.append(residue)

        return residues


def validate(path: str) -> str:
    logger.debug(f"Starting validation of {path}")
    pdb_id = get_pdb_id(path) or "unknown_pdb_id"
    model_paths = split_models(path)
    output_models = []
    status = Status()

    mp = MolProbity()

    for model_num, model_path in model_paths:
        model = Model(number=model_num)

        try:
            model.residues = mp.residue_analysis(model_path)
        except ValidationError:
            status.residue_analysis = False

        output_models.append(model)

    status = Status()
    result = Result(status=status, pdb_id=pdb_id, models=output_models)
    return result.model_dump_json(exclude_none=True)
