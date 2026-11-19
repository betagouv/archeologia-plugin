"""Arbre des couches d'une analyse (2026-11-18), contrôlé sur un projet ÉCRIT par QGIS.

``tests/fixtures/arbre_analyse.qgs`` est l'arbre que ``ui/qgs_writer.write_validation_project`` a écrit
pour un livrable synthétique (MNT, LD, SVF, couverture, densité, une couche de détection, zones mal
couvertes) : ``python-qgis.bat dev/rendu_hors_ecran.py arbre --fixture tests/fixtures/arbre_analyse.qgs``,
qui contrôle aussi le chargement en direct et le rechargement d'une analyse rangée à l'ancienne, sous les
deux QGIS. À refaire si l'arbre change.
"""
from __future__ import annotations

from pathlib import Path

from app.services import nom_analyse as na

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "arbre_analyse.qgs"
TITRE = "Synthèse · arbre — 18/11/2026 10:00"


def _groupe(arbre, nom):
    return next(e for e in arbre["enfants"] if not e["couche"] and e["nom"] == nom)


def test_le_projet_ecrit_porte_l_arbre_voulu():
    texte = FIXTURE.read_text(encoding="utf-8")
    analyse = _groupe(na.arbre_du_qgs(texte), TITRE)
    assert [e["nom"] for e in analyse["enfants"]] == ["Qualité de la donnée", "Structures", "Indices"]

    indices = _groupe(analyse, "Indices")
    assert indices["exclusif"] and 'mutually-exclusive="1"' in texte
    assert [(e["nom"].split(" · ")[0], e["coche"]) for e in indices["enfants"]] == [
        ("SVF", False), ("LD", True), ("MNT", False)]                 # LD seul coché, MNT en dernier

    qualite = _groupe(analyse, "Qualité de la donnée")
    assert not qualite["exclusif"]                                     # plusieurs cases cochables
    assert [(e["nom"].split(" · ")[0], e["coche"]) for e in qualite["enfants"]] == [
        ("Zones mal couvertes (<30 %)", True), ("Couverture", False), ("Densité", False)]
    assert na.ecarts_arbre(na.arbre_du_qgs(texte), TITRE) == []


def test_le_controle_voit_l_arbre_d_avant():
    """L'arbre d'avant le 2026-11-18 (couche QA en tête du groupe, couverture dans « Indices », pas
    d'exclusivité) n'est pas conforme : le contrôle de dev/rendu_hors_ecran.py arbre échouerait."""
    def c(nom, coche=True):
        return {"nom": nom, "couche": True, "coche": coche, "exclusif": False, "enfants": []}

    ancien = {"nom": "", "couche": False, "coche": True, "exclusif": False, "enfants": [
        {"nom": TITRE, "couche": False, "coche": True, "exclusif": False, "enfants": [
            c("Zones mal couvertes (<30 %)"),
            {"nom": "Structures", "couche": False, "coche": True, "exclusif": False, "enfants": [c("Enclos")]},
            {"nom": "Indices", "couche": False, "coche": True, "exclusif": False,
             "enfants": [c("LD · Structures en relief · A15"), c("Couverture · Couverture du sol mesuré"),
                         c("MNT · Relief nu")]},
        ]}]}
    ecarts = na.ecarts_arbre(ancien, TITRE)
    assert any("hors des groupes" in e for e in ecarts)
    assert "« Indices » n'est pas exclusif" in ecarts
    assert any("produit de qualité dans « Indices »" in e for e in ecarts)
    assert any("cochées" in e for e in ecarts)
    assert na.ecarts_arbre(ancien, "autre") == ["groupe de l'analyse « autre » absent"]


def test_chargement_en_direct_et_qgs_rangent_par_la_meme_regle():
    src = Path(__file__).resolve().parents[2] / "src" / "ui"
    loader = (src / "layer_loader.py").read_text(encoding="utf-8")
    writer = (src / "qgs_writer.py").read_text(encoding="utf-8")
    for code in (loader, writer):
        assert "est_qualite(" in code and "groupe_qualite(" in code and "regler_indices(" in code
    assert "setIsMutuallyExclusive(True, indice_coche(types))" in loader
    # une couche déjà chargée est rangée dans son nouveau groupe, jamais doublée
    assert "_ranger(root, existante, cible" in loader
