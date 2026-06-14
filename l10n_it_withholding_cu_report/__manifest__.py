# Copyright 2026 OdooManager.cloud
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "ITA - Ritenute per percipiente (dettaglio CU)",
    "version": "18.0.1.0.0",
    "category": "Accounting/Localizations/Italy",
    "summary": "Registro di dettaglio delle ritenute d'acconto per percipiente, "
    "causale e anno (base per la Certificazione Unica).",
    "author": "OdooManager.cloud",
    "website": "https://odoomanager.cloud",
    "license": "AGPL-3",
    "depends": [
        "account",
        "l10n_it_edi_withholding",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/withholding_cu_report_rules.xml",
        "views/withholding_cu_report_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
