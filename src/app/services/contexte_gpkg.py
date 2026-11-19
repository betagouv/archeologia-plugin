"""Écrit le contexte moderne dans les GeoPackages de détections d'un traitement terminé.

Appelé par ``finalize_pipeline`` (fil de travail, donc ni QGIS ni Qt ici) une fois les GeoPackages
définitifs, et par ``dev/contexte_moderne.py`` sur un traitement déjà fait. Trois temps :

1. lire les géométries de chaque couche de détections (``pyogrio``, colonnes réduites au strict
   nécessaire) ; les couches de synthèse (zones de regroupement, champ ``nb_detect``) sont laissées ;
2. télécharger une seule fois les six données du croisement sur l'emprise de toutes les
   détections (:mod:`contexte_croisement`) ;
3. écrire les cinq champs par SQLite (``ALTER TABLE`` + ``UPDATE`` par ``fid``) : la couche n'est pas
   réécrite, aucun autre champ ne bouge — même discipline que :func:`fiabilite.recompter_effectifs`.

Le champ ``fiabilite`` n'est jamais touché : bilan, rapport et fiabilité observée en dépendent.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from . import contexte_croisement as cc
from . import contexte_moderne as cm
from .fiabilite import recompter_ecartes

#: Type SQLite de chaque champ.
TYPES = {"contexte_moderne": "TEXT", "contexte_info": "TEXT", "contexte_dist_m": "INTEGER",
         "contexte_part": "INTEGER", "contexte_source": "TEXT"}
SCR_ACCEPTES = ("EPSG:2154",)


@dataclass
class Bilan:
    """Ce que le croisement a fait, pour le journal et la trace du traitement."""
    total: int = 0
    marquees: int = 0
    informees: int = 0
    par_structure: Dict[str, Tuple[int, int, int]] = field(default_factory=dict)   # slug → (total, marquées, informées)
    source: str = ""
    motif: str = ""        # non vide = croisement non fait, et pourquoi

    @property
    def phrase(self) -> str:
        return self.motif or cm.resume(self.marquees, self.informees, self.total)

    def en_dict(self) -> dict:
        return {"total": self.total, "marquees": self.marquees, "informees": self.informees,
                "par_structure": {k: list(v) for k, v in self.par_structure.items()},
                "source": self.source, "motif": self.motif}


def couches_de_detections(det_dir: Path) -> List[Tuple[Path, str]]:
    """``(gpkg, couche)`` de chaque couche de détections sous ``livrable/detections`` (``_technique``
    exclu), synthèses de regroupement exclues."""
    out = []
    for gpkg in sorted(Path(det_dir).rglob("*.gpkg")):
        if any(p.startswith("_") for p in gpkg.relative_to(det_dir).parts[:-1]):
            continue
        try:
            with sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True) as con:
                noms = [r[0] for r in con.execute(
                    "SELECT table_name FROM gpkg_contents WHERE data_type = 'features' ORDER BY table_name")]
                for nom in noms:
                    colonnes = {r[1] for r in con.execute(f'PRAGMA table_info("{nom}")')}
                    if "nb_detect" not in colonnes:
                        out.append((gpkg, nom))
        except sqlite3.Error:
            continue
    return out


def lire_geometries(gpkg: Path, couche: str) -> Tuple[List[int], list]:
    """``(fids, géométries shapely)`` d'une couche, sans ses attributs."""
    import pyogrio

    df = pyogrio.read_dataframe(str(gpkg), layer=couche, columns=[], fid_as_index=True)
    return [int(i) for i in df.index], list(df.geometry)


def _enveloppe(blob):
    """``(vide, minx, maxx, miny, maxy)`` d'une géométrie GeoPackage, lue dans son en-tête (ou, sans
    enveloppe déclarée, dans la géométrie elle-même)."""
    import struct

    if blob is None:
        return True, None, None, None, None
    b = bytes(blob)
    if len(b) < 8 or b[:2] != b"GP":
        return True, None, None, None, None
    drapeaux = b[3]
    ordre = "<" if drapeaux & 1 else ">"
    vide = bool(drapeaux & 0b10000)
    if (drapeaux >> 1) & 0b111 and len(b) >= 40:
        minx, maxx, miny, maxy = struct.unpack(ordre + "4d", b[8:40])
        return vide, minx, maxx, miny, maxy
    from shapely import wkb

    taille = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get((drapeaux >> 1) & 0b111, 0)
    g = wkb.loads(b[8 + taille:])
    if g.is_empty:
        return True, None, None, None, None
    x0, y0, x1, y1 = g.bounds
    return False, x0, x1, y0, y1


def _fonctions_spatiales(con: sqlite3.Connection) -> None:
    """Les fonctions qu'appellent les déclencheurs d'index spatial écrits par GDAL. SQLite exige
    qu'elles existent dès qu'une mise à jour touche la table, même si le déclencheur ne s'exécute pas
    (seuls les champs contexte_* changent, jamais la géométrie ni le fid)."""
    con.create_function("ST_IsEmpty", 1, lambda g: 1 if _enveloppe(g)[0] else 0, deterministic=True)
    for i, nom in enumerate(("ST_MinX", "ST_MaxX", "ST_MinY", "ST_MaxY"), start=1):
        con.create_function(nom, 1, lambda g, i=i: _enveloppe(g)[i], deterministic=True)


def ecrire_champs(gpkg: Path, couche: str, fids: Sequence[int], valeurs: Sequence[Mapping[str, object]],
                  types: Mapping[str, str] = TYPES) -> None:
    """Ajoute les champs manquants puis écrit les valeurs, ligne par ligne (``fid``), en une transaction.
    ``types`` = les champs écrits et leur type SQLite (ceux du contexte moderne par défaut)."""
    con = sqlite3.connect(str(gpkg))
    try:
        _fonctions_spatiales(con)
        cle = next((r[1] for r in con.execute(f'PRAGMA table_info("{couche}")') if r[5]), "fid")
        existants = {r[1] for r in con.execute(f'PRAGMA table_info("{couche}")')}
        for nom in types:
            if nom not in existants:
                con.execute(f'ALTER TABLE "{couche}" ADD COLUMN "{nom}" {types[nom]}')
        affect = ", ".join(f'"{n}" = ?' for n in types)
        con.executemany(f'UPDATE "{couche}" SET {affect} WHERE "{cle}" = ?',
                        [tuple(v[n] for n in types) + (f,) for f, v in zip(fids, valeurs)])
        con.commit()
    finally:
        con.close()


def _structure(det_dir: Path, gpkg: Path, couche: str) -> str:
    """Slug de l'entité (dossier) et nom de couche : ce que lit :func:`contexte_moderne.est_talus`. Sans la
    qualification d'une comparaison A/B (``<slug>--<modèle>``, ``<libellé> — <modèle>``) : le nom du modèle
    (« lineaires_… ») rendait linéaire une structure ponctuelle, jamais écartée (2026-11-18)."""
    rel = gpkg.relative_to(det_dir).parts
    slug = (rel[0] if len(rel) > 1 else gpkg.stem).split("--")[0]
    return f"{slug} {couche.split(' — ')[0]}"


#: Repli si le catalogue livré est illisible ; un test vérifie qu'ils sont ceux du catalogue.
TITRES_PAR_DEFAUT = {cm.BATIMENT: "Bâtiments", cm.EAU: "Surfaces en eau et mares", cm.COURS_EAU: "Cours d'eau",
                     cm.HABITATION: "Zones d'habitation", cm.ROND_POINT: "Ronds-points",
                     cm.ROUTE: "Routes et chemins", cm.VOIE_FERREE: "Voies ferrées",
                     cm.TALUS_IGN: "Talus, levées et fronts de carrière", cm.CANALISATION: "Canalisations",
                     cm.MONUMENT: "Monuments historiques", cm.PLU_ZONE: "Archéologie des PLU (zones)",
                     cm.PLU_POINT: "Archéologie des PLU (points)",
                     cm.ZPPA_BRETAGNE: "Zones de présomption (Bretagne)",
                     cm.ZPPA_AURA: "Zones de présomption (Auvergne-Rhône-Alpes)",
                     cm.ZPPA_CVL: "Zones de présomption (Centre-Val de Loire)"}


def titres_catalogue() -> Dict[str, str]:
    """Le titre, dans le Catalogue des flux, de la donnée qui correspond à chaque source du croisement."""
    from . import fonds_publics as fp

    try:
        _service, fonds = fp.charger(Path(__file__).resolve().parents[3] / fp.CATALOGUE)
    except (OSError, ValueError):
        return dict(TITRES_PAR_DEFAUT)
    # Les couches du bouton « Ajouter le contexte moderne » (dont « Ronds-points », 2026-11-18), puis le
    # catalogue, qui a le dernier mot pour une donnée qu'il porte aussi.
    par_id = {f.id: f.titre for _g, f, _v in fp.couches_contexte(fonds)}
    par_id.update({f.id: f.titre for f in fonds if f.objets})
    return {s: par_id.get(i, TITRES_PAR_DEFAUT[s]) for s, i in cc.ID_CATALOGUE.items()}


#: Couche du GeoPackage local (= source du croisement) par fond du bouton « Ajouter le contexte moderne ».
COUCHE_PAR_FOND = {fond: source for source, fond in cc.ID_CATALOGUE.items()}


def chemin_contexte(det_dir: Path) -> Path:
    """``livrable/contexte/contexte_moderne.gpkg`` : les objets qui ont servi au croisement."""
    return Path(det_dir).parent / "contexte" / "contexte_moderne.gpkg"


def garder_objets(det_dir: Path, objets: Mapping[str, Sequence[Mapping]]) -> Optional[Path]:
    """Écrit les objets téléchargés dans le livrable, une couche par donnée qui en a (2026-11-13) : le
    bouton « Ajouter le contexte moderne » les lit sans réseau, et le livrable garde ce qui a décidé.
    Remplace le fichier d'un traitement précédent ; rend ``None`` s'il n'y a rien à écrire."""
    import geopandas as gpd
    from shapely.geometry import shape

    def texte(v):       # attributs en texte : une colonne mêlant booléens et vides ne s'écrit pas
        if isinstance(v, bool):
            return "oui" if v else "non"
        return None if v is None else str(v)

    chemin = chemin_contexte(det_dir)
    chemin.unlink(missing_ok=True)
    for source, liste in objets.items():
        lignes, geoms = [], []
        for o in liste:
            try:
                g = shape(o["geometry"])
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if g.is_empty:
                continue
            geoms.append(g)
            lignes.append({k: texte(v) for k, v in (o.get("properties") or {}).items()})
        if not geoms:
            continue
        chemin.parent.mkdir(parents=True, exist_ok=True)
        gpd.GeoDataFrame(lignes, geometry=geoms, crs="EPSG:2154").to_file(
            chemin, layer=source, driver="GPKG", engine="pyogrio")
    return chemin if chemin.is_file() else None


def marquer(det_dir: Path, lire_json: Callable[[str], Mapping], *, crs: str = "EPSG:2154",
            annule: Callable[[], bool] = lambda: False, aujourd_hui: Optional[str] = None,
            journal: Callable[[str], None] = lambda m: None) -> Bilan:
    """Croise toutes les détections du traitement et écrit leurs champs. Ne lève jamais pour le réseau :
    une erreur de téléchargement laisse les GeoPackages tels quels et renseigne ``Bilan.motif``."""
    det_dir = Path(det_dir)
    if (crs or "").upper() not in SCR_ACCEPTES:
        return Bilan(motif=f"Contexte moderne non vérifié : la BD TOPO ne couvre que la France ({crs}).")
    couches = couches_de_detections(det_dir)
    lues = []
    for gpkg, couche in couches:
        fids, geoms = lire_geometries(gpkg, couche)
        if fids:
            lues.append((gpkg, couche, fids, geoms))
    if not lues:
        return Bilan()
    emprises = [g.bounds for _g, _c, _f, geoms in lues for g in geoms if g is not None and not g.is_empty]
    carres = {m: cc.cellules(emprises, m) for m in {cm.marge(s) for s in cc.COUCHES}}
    structures = {_structure(det_dir, gpkg, couche) for gpkg, couche, _f, _g in lues}
    # seulement les données qu'au moins une structure du traitement consulte (pas de route sans linéaire)
    voulues = [s for s in cc.COUCHES if any(cm.consulte(s, st) for st in structures)
               and any(cc.dans_emprise(s, b) for b in carres[cm.marge(s)])]   # pas la Bretagne en Moselle
    titres = titres_catalogue()
    noms = ", ".join(titres[s][:1].lower() + titres[s][1:] for s in voulues)
    n = len(carres[cm.RAYON_PROCHE])
    journal(f"Contexte moderne : lecture de la BD TOPO de l'IGN et du patrimoine connu autour des détections "
            f"({noms} ; {n} requête{'s' if n > 1 else ''} par donnée)…")
    objets = {}
    for source in voulues:
        try:
            objets[source] = cc.telecharger(source, carres[cm.marge(source)], lire_json, annule)
        except Exception as exc:                   # noqa: BLE001 — réseau : jamais d'échec du traitement
            if source not in cc.FACULTATIVES:
                return Bilan(motif=f"Contexte moderne non vérifié : la BD TOPO de l'IGN est injoignable "
                                   f"({type(exc).__name__}).")
            objets[source] = []
            journal(f"Contexte moderne : « {titres[source]} » non consultée, le service ne répond pas "
                    f"({type(exc).__name__}) ; le reste du croisement est fait.")
    if annule():
        return Bilan(motif="Contexte moderne non vérifié : traitement annulé.")
    try:
        garder_objets(det_dir, objets)
    except Exception as exc:                       # noqa: BLE001 — fichier verrouillé, disque : le marquage continue
        journal(f"Contexte moderne : données non enregistrées dans le dossier du traitement ({type(exc).__name__}).")
    jour = aujourd_hui or date.today().isoformat()
    bilan = Bilan(source=cm.libelle_source(jour, list(dict.fromkeys(titres[s] for s in voulues)), cm.base_de(voulues)))
    for gpkg, couche, fids, geoms in lues:
        structure = _structure(det_dir, gpkg, couche)
        # « rien à proximité » nomme les données consultées pour cette structure
        consultees = [s for s in voulues if cm.consulte(s, structure)]
        source = cm.libelle_source(jour, list(dict.fromkeys(titres[s] for s in consultees)), cm.base_de(consultees))
        valeurs = cc.croiser(geoms, objets, structure, source, titres, jour)
        ecrire_champs(gpkg, couche, fids, valeurs)
        recompter_ecartes(gpkg)                 # le bilan « Par où commencer » montre les écartées à part
        m = sum(1 for v in valeurs if v["contexte_moderne"])
        i = sum(1 for v in valeurs if v["contexte_info"] and not v["contexte_moderne"])
        slug = gpkg.relative_to(det_dir).parts[0] if len(gpkg.relative_to(det_dir).parts) > 1 else gpkg.stem
        t0, m0, i0 = bilan.par_structure.get(slug, (0, 0, 0))
        bilan.par_structure[slug] = (t0 + len(valeurs), m0 + m, i0 + i)
        bilan.total += len(valeurs)
        bilan.marquees += m
        bilan.informees += i
    return bilan
