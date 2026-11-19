"""Rail de l'assistant, étape 6 « Résultats » (2026-11-18, vu par MCP dans QGIS 3.44).

Le registre des traitements n'était relu qu'en entrant à l'étape 6 : à l'ouverture comme après un
traitement, le rail disait « aucun traitement » alors que le poste en connaissait 23. Garde-fous lus
dans le code (src/ui n'est pas importable sans QGIS), comme test_reset_defauts_ui.py.
"""
from __future__ import annotations

import ast
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "src" / "ui"


def _methode(fichier: Path, classe: str, nom: str) -> ast.FunctionDef:
    arbre = ast.parse(fichier.read_text(encoding="utf-8"))
    cls = next(n for n in arbre.body if isinstance(n, ast.ClassDef) and n.name == classe)
    return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == nom)


def test_fin_de_traitement_relit_le_registre_et_le_rail():
    corps = ast.unparse(_methode(UI / "wizard_dialog.py", "WizardDialog", "_on_run_finished"))
    assert "_resultats_page.rafraichir()" in corps
    assert "set_sub(6" in corps or "_refresh_rail_subs()" in corps


def test_rail_muet_tant_que_le_registre_n_est_pas_lu():
    corps = ast.unparse(_methode(UI / "steps" / "step_6_resultats.py", "ResultatsPage", "summary"))
    assert "_lu" in corps, "summary() doit rendre '' avant la première lecture, pas « aucun traitement »"
