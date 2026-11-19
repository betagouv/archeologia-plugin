"""Les étiquettes des vecteurs ponctuels du Catalogue des flux ont un halo (2026-11-19).

Sans halo, le texte gris foncé par défaut de QGIS se perd sur le relief gris (LD, SVF, ombrages) : constaté
sur les forages, les gîtes et les seuils posés sur le LD. ``src/ui`` ne s'importe pas hors de QGIS : on lit
le source de ``FondsPage._couche_objets``.
"""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src" / "ui" / "fonds_page.py"


def _corps(nom: str) -> str:
    arbre = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.FunctionDef) and noeud.name == nom:
            return ast.get_source_segment(SOURCE.read_text(encoding="utf-8"), noeud)
    raise AssertionError(f"{nom} introuvable")


def test_les_etiquettes_des_points_ont_un_halo():
    corps = _corps("_couche_objets")
    assert "QgsPalLayerSettings()" in corps
    assert "setBuffer" in corps and "setEnabled(True)" in corps, "étiquette sans halo : illisible sur le relief"
    assert "setFormat" in corps
