"""
IRS Form 8949 Sales and Dispositions Report Exporter.
Conforms to Section 7 of the Technical Design Document.

Outputs tax-year capital asset dispositions with IRC §1091 adjustment codes ('W')
and disallowed loss amounts formatted for standard tax preparation workflows.
"""

import csv
import io
from typing import Any, Dict, List, Optional

from src.ledger.cost_basis import ClosedDisposition


class Form8949Exporter:
    """
    Generates IRS Form 8949 (Sales and Other Dispositions of Capital Assets) export datasets.
    """

    FORM_8949_HEADERS: List[str] = [
        "1a_description",
        "1b_date_acquired",
        "1c_date_sold",
        "1d_proceeds",
        "1e_cost_basis",
        "1f_code",
        "1g_adjustment_amount",
        "1h_gain_loss",
    ]

    @classmethod
    def generate_records(cls, dispositions: List[ClosedDisposition]) -> List[Dict[str, Any]]:
        """Transforms ClosedDisposition records into Form 8949 standard row items."""
        records: List[Dict[str, Any]] = []

        for d in dispositions:
            desc = f"{d.quantity:.2f} shs {d.ticker}"
            code = "W" if d.is_wash_sale else ""
            adj_amount = f"{d.disallowed_loss:.2f}" if d.is_wash_sale and d.disallowed_loss > 0 else ""

            records.append({
                "1a_description": desc,
                "1b_date_acquired": d.acquired_date.isoformat(),
                "1c_date_sold": d.sold_date.isoformat(),
                "1d_proceeds": round(d.proceeds, 2),
                "1e_cost_basis": round(d.cost_basis, 2),
                "1f_code": code,
                "1g_adjustment_amount": round(d.disallowed_loss, 2) if d.is_wash_sale else 0.0,
                "1h_gain_loss": round(d.net_gain_loss, 2),
            })

        return records

    @classmethod
    def export_csv(
        cls,
        dispositions: List[ClosedDisposition],
        filepath: Optional[str] = None,
    ) -> str:
        """
        Exports dispositions as Form 8949 standard CSV.
        Returns CSV text string and optionally writes to filepath.
        """
        records = cls.generate_records(dispositions)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=cls.FORM_8949_HEADERS)
        writer.writeheader()

        for rec in records:
            writer.writerow(rec)

        csv_str = buffer.getvalue()
        if filepath:
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                f.write(csv_str)

        return csv_str
