"""Nom de l'analyse (0.19.0) — module PUR.

Champ de l'étape 1 (``app.files.nom_analyse``), proposé d'après le dossier de sortie
(« <dossier parent> · <dossier de sortie> ») tant que l'utilisateur ne l'a pas écrit
lui-même ; une configuration sans le champ (antérieure, ou champ vidé) retombe sur la
proposition. Le nom suivi de la date du traitement est le **groupe parent** des couches
dans QGIS (« Ajouter au projet QGIS courant », étape 6, ``livrable/projet.qgs``) ; il titre
le rapport et la trace (``traitement.json`` / ``metadata_*.json`` : ``nom_analyse``).

Les fonctions d'arbre ne connaissent que l'interface de ``QgsLayerTreeGroup`` qu'elles
appellent (``findGroup``, ``insertGroup``, ``addGroup``, ``children``, ``removeChildNode``,
``customProperty``) : ``ui/layer_loader`` et ``ui/qgs_writer`` leur passent la racine de leur
projet, d'où le même arbre dans les deux, testé ici sans QGIS.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from .finalize_service import GROUPE_STRUCTURES

SEPARATEUR = " · "
GROUPE_INDICES = "Indices"
#: Groupe des produits de contrôle (2026-11-18) : le libellé de la section de l'étape 2 qui les propose.
GROUPE_QUALITE = "Qualité de la donnée"
#: Ordre des groupes dans celui d'une analyse, quel que soit l'ordre où ils sont créés.
ORDRE_GROUPES = (GROUPE_QUALITE, GROUPE_STRUCTURES, GROUPE_INDICES)
#: Marque posée sur le groupe d'une analyse : son titre d'origine. Retrouve le groupe même
#: renommé par l'utilisateur, et distingue un groupe du plugin d'un groupe de même nom.
PROPRIETE = "archeologia/analyse"


def nom_par_defaut(output_dir: Any) -> str:
    """« <parent> · <dossier> » (``…\\be_vl\\indices`` → « be_vl · indices ») ; le dossier
    seul sous la racine d'un lecteur ; "" sans dossier."""
    parts = [p for p in re.split(r"[\\/]+", str(output_dir or "").strip()) if p and not p.endswith(":")]
    return SEPARATEUR.join(parts[-2:])


def est_automatique(texte: str, output_dir: Any) -> bool:
    """Le nom suit-il encore le dossier ? Oui s'il est vide ou égal à la proposition."""
    t = str(texte or "").strip()
    return not t or t == nom_par_defaut(output_dir)


def nom_de_config(config: Optional[dict]) -> str:
    files = ((config or {}).get("app") or {}).get("files") or {}
    return str(files.get("nom_analyse") or "").strip() or nom_par_defaut(files.get("output_dir"))


def titre_groupe(nom: str, date_iso: str) -> str:
    """« <nom> — JJ/MM/AAAA HH:MM » (date du traitement, celle de la trace)."""
    nom = str(nom or "").strip() or "Analyse"
    try:
        return f"{nom} — {_dt.datetime.fromisoformat(str(date_iso)).strftime('%d/%m/%Y %H:%M')}"
    except ValueError:
        return nom


def titre_du_livrable(output_dir: Any) -> str:
    """Titre du groupe d'un traitement, lu dans ``livrable/traitement.json`` : la vue de fin et
    l'étape 6 nomment ainsi le même traitement de la même façon (recharger ne duplique rien)."""
    try:
        trace = json.loads((Path(output_dir) / "livrable" / "traitement.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        trace = {}
    if not isinstance(trace, dict):
        trace = {}
    return titre_groupe(str(trace.get("nom_analyse") or "") or nom_par_defaut(output_dir), str(trace.get("date") or ""))


# ── arbre des couches ───────────────────────────────────────────────
def groupe_analyse(root, titre: str):
    """Le groupe de l'analyse ``titre`` (retrouvé par sa marque), sinon créé en haut de l'arbre.
    Sans titre : la racine (arbre à plat d'avant 0.19.0)."""
    if not titre:
        return root
    for n in root.children():
        if n.customProperty(PROPRIETE) == titre:
            return n
    g = root.insertGroup(0, titre)
    g.setCustomProperty(PROPRIETE, titre)
    return g


def _groupe_ordonne(parent, nom: str):
    """Le groupe ``nom`` de ``parent``, sinon créé juste après ceux qui le précèdent dans
    :data:`ORDRE_GROUPES` (en tête s'il n'y en a pas)."""
    g = parent.findGroup(nom)
    if g is not None:
        return g
    avant = ORDRE_GROUPES[:ORDRE_GROUPES.index(nom)]
    rang = 0
    for i, n in enumerate(parent.children()):
        if n.name() in avant:
            rang = i + 1
    return parent.insertGroup(rang, nom)


def groupe_qualite(parent):
    """« Qualité de la donnée » (en tête du groupe d'une analyse : couche des zones mal couvertes,
    densité et couverture, 2026-11-18) ; à la racine, à plat comme les rasters."""
    if parent.customProperty(PROPRIETE) is None:
        return parent
    return _groupe_ordonne(parent, GROUPE_QUALITE)


def groupe_structures(parent, sous_groupe: str = ""):
    """« Structures » (sous « Qualité de la donnée »), et le sous-groupe d'une dérivée ou d'une comparaison."""
    s = _groupe_ordonne(parent, GROUPE_STRUCTURES)
    return (s.findGroup(sous_groupe) or s.insertGroup(0, sous_groupe)) if sous_groupe else s


def groupe_indices(parent):
    """« Indices » (sous les structures) dans le groupe d'une analyse ; à la racine, les rasters
    restent à plat. Groupe exclusif (un indice affiché à la fois) : :func:`indice_coche`."""
    if parent.customProperty(PROPRIETE) is None:
        return parent
    return _groupe_ordonne(parent, GROUPE_INDICES)


def est_qualite(type_produit: str) -> bool:
    """Le produit (dossier d'image : ``COUVERTURE``, ``DENSITE``…) va-t-il dans « Qualité de la donnée » ?
    La liste est celle de la section de l'étape 2 (``indices_model.quality_keys``)."""
    from .indices_model import quality_keys

    return str(type_produit or "").upper() in quality_keys()


def indice_coche(types: Sequence[str]) -> int:
    """Rang de l'indice coché dans le groupe exclusif « Indices » : le LD (sigle avant le premier « _ »),
    sinon le premier de la liste (2026-11-18)."""
    for i, t in enumerate(types):
        if str(t or "").split("_")[0].upper() == "LD":
            return i
    return 0


def arbre_du_qgs(texte: str) -> dict:
    """L'arbre des couches d'un ``.qgs`` (``<layer-tree-group>``) en dictionnaires ``{nom, couche, coche,
    exclusif, enfants}`` : ce que :func:`ecarts_arbre` contrôle, comme l'arbre d'un projet chargé."""
    import xml.etree.ElementTree as ET

    def noeud(el) -> dict:
        return {"nom": el.get("name", ""), "couche": el.tag == "layer-tree-layer",
                "coche": el.get("checked") == "Qt::Checked", "exclusif": el.get("mutually-exclusive") == "1",
                "enfants": [noeud(c) for c in el if c.tag in ("layer-tree-group", "layer-tree-layer")]}

    return noeud(ET.fromstring(texte).find("layer-tree-group"))


def _sigle(nom_couche: str) -> str:
    return str(nom_couche).split(" · ")[0]


def ecarts_arbre(arbre: dict, titre: str) -> list:
    """Les écarts entre l'arbre d'une analyse et l'arbre voulu (2026-11-18) : groupes « Qualité de la donnée »,
    « Structures », « Indices » dans cet ordre ; « Indices » exclusif, une seule couche cochée (LD, sinon la
    première), sans produit de qualité, MNT en dernier ; « Qualité de la donnée » : zones mal couvertes en
    tête, densité et couverture décochées. Liste vide = conforme."""
    from .indices_model import quality_keys
    from .vocabulaire import titre_dossier_image

    sigles_qualite = {_sigle(titre_dossier_image(k)) for k in quality_keys()}
    g = next((e for e in arbre["enfants"] if not e["couche"] and e["nom"] == titre), None)
    if g is None:
        return [f"groupe de l'analyse « {titre} » absent"]
    ecarts = []
    groupes = [e["nom"] for e in g["enfants"] if not e["couche"]]
    if groupes != [n for n in ORDRE_GROUPES if n in groupes]:
        ecarts.append(f"groupes dans le désordre : {groupes}")
    a_plat = [e["nom"] for e in g["enfants"] if e["couche"]]
    if a_plat:
        ecarts.append(f"couches hors des groupes : {a_plat}")
    par_nom = {e["nom"]: e for e in g["enfants"] if not e["couche"]}
    indices = par_nom.get(GROUPE_INDICES)
    if indices is not None:
        couches = [e for e in indices["enfants"] if e["couche"]]
        sigles = [_sigle(e["nom"]) for e in couches]
        if not indices["exclusif"]:
            ecarts.append("« Indices » n'est pas exclusif")
        cochees = [e["nom"] for e in couches if e["coche"]]
        if couches and cochees != [couches[indice_coche(sigles)]["nom"]]:
            ecarts.append(f"« Indices » : cochées {cochees}, attendu {couches[indice_coche(sigles)]['nom']}")
        if "MNT" in sigles and sigles[-1] != "MNT":
            ecarts.append("MNT pas en dernier dans « Indices »")
        if sigles_qualite & set(sigles):
            ecarts.append(f"produit de qualité dans « Indices » : {sorted(sigles_qualite & set(sigles))}")
    qualite = par_nom.get(GROUPE_QUALITE)
    if qualite is not None:
        couches = [e for e in qualite["enfants"] if e["couche"]]
        for e in couches:
            if _sigle(e["nom"]) in sigles_qualite and e["coche"]:
                ecarts.append(f"« {e['nom']} » cochée")
        qa = [i for i, e in enumerate(couches) if e["nom"].startswith("Zones mal couvertes")]
        if qa and qa != [0]:
            ecarts.append("zones mal couvertes pas en tête de « Qualité de la donnée »")
    return ecarts


def _vider(groupe, est_groupe: Callable[[Any], bool]) -> None:
    for n in list(groupe.children()):
        if est_groupe(n) and not n.children():
            groupe.removeChildNode(n)


def retirer_groupes_vides(root, est_groupe: Callable[[Any], bool]) -> None:
    """Après la purge (par chemin) : retire les groupes du plugin qu'elle a vidés — groupe d'une
    analyse (marqué), ses « Structures » (et leurs sous-groupes) et « Indices », l'ancien
    « Structures » de la racine. Jamais un groupe de l'utilisateur, jamais un groupe peuplé."""
    for g in [n for n in root.children() if est_groupe(n)]:
        if g.customProperty(PROPRIETE) is not None:
            for n in list(g.children()):
                if est_groupe(n) and n.name() == GROUPE_STRUCTURES:
                    _vider(n, est_groupe)
                if est_groupe(n) and n.name() in ORDRE_GROUPES and not n.children():
                    g.removeChildNode(n)
        elif g.name() == GROUPE_STRUCTURES:
            _vider(g, est_groupe)
        else:
            continue
        if not g.children():
            root.removeChildNode(g)
