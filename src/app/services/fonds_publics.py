"""Fonds de carte publics de l'onglet « Catalogue des flux », pur et testable.

Ce sont des couches WMTS **sans clé** de la Géoplateforme (cartes anciennes, photos aériennes,
Plan IGN…), les mêmes partout en France : elles ne se rangent pas par département comme nos indices
(:mod:`visu_catalogue`), mais par **époque**. Le catalogue `data/fonds_publics/fonds.json` est
versionné et livré (écrit par `dev/fonds_publics.py`) ; l'ordre du fichier est l'ordre d'affichage.

Ni Qt ni QGIS ici : la page vit dans ``src/ui/fonds_page.py``.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

CATALOGUE = Path("data") / "fonds_publics" / "fonds.json"
#: Groupes de l'arbre des couches. Le premier est **mutuellement exclusif** : un fond est une image
#: opaque, deux fonds cochés ne montreraient que celui du dessus. Les repères sont transparents.
GROUPE_FONDS = "Fonds de carte"
GROUPE_REPERES = "Repères"
#: Les vecteurs : contours cliquables, plusieurs visibles à la fois, au-dessus des repères.
GROUPE_OBJETS = "Données vectorielles"
#: Propriété posée sur chaque couche ouverte par la page : c'est elle qui dit « à nous », y compris
#: dans un projet rouvert (jamais le nom de la couche, que l'utilisateur peut changer).
#: Groupe du bouton « Ajouter le contexte moderne » (fin de traitement), rangé par famille.
GROUPE_CONTEXTE = "Contexte moderne"
#: Ses couches (2026-11-12, sélection validée par l'utilisateur sur les Vosges et Fénétrange) : par famille,
#: ``(identifiant, titre, couche du service, géométrie, champ montré au clic, filtre, cochée)``. Toutes sont
#: ajoutées ; seules les cochées se dessinent d'emblée, les autres attendent que l'utilisateur les coche.
#: Un identifiant du catalogue (« batiments »…) reprend sa couche, pour ne pas la charger deux fois.
_T = "BDTOPO_V3:"
CONTEXTE_MODERNE = (
    ("Routes et transports", "#d7301f", (
        ("ctx_ronds_points", "Ronds-points", _T + "troncon_de_route", "ligne", "nature", "\"nature\" = 'Rond-point'", True),
        ("ctx_ronds_points_centres", "Ronds-points (centres, BD CARTO)", "BDCARTO_V5:rond_point", "point", "", "", False),
        ("routes_chemins", "Routes et chemins", _T + "troncon_de_route", "ligne", "nature", "", False),
        ("ctx_voies_ferrees", "Voies ferrées", _T + "troncon_de_voie_ferree", "ligne", "nature", "", False),
        ("ctx_equipements_transport", "Équipements de transport (parkings, aires, péages)",
         _T + "equipement_de_transport", "surface", "nature", "", False),
        ("ctx_pistes_aerodrome", "Pistes d'aérodrome", _T + "piste_d_aerodrome", "surface", "nature", "", False),
        ("ctx_transport_cable", "Transport par câble", _T + "transport_par_cable", "ligne", "nature", "", False),
    )),
    ("Bâti et constructions", "#a6611a", (
        ("batiments", "Bâtiments", _T + "batiment", "surface", "nature", "", True),
        ("ctx_reservoirs", "Réservoirs, châteaux d'eau, bassins", _T + "reservoir", "surface", "nature", "", True),
        ("ctx_cimetieres", "Cimetières", _T + "cimetiere", "surface", "nature", "", True),
        ("ctx_constructions_surfaciques", "Constructions surfaciques (barrages, dalles, ruines…)",
         _T + "construction_surfacique", "surface", "nature", "", False),
        ("ctx_constructions_lineaires", "Constructions linéaires (murs, digues, quais…)",
         _T + "construction_lineaire", "ligne", "nature", "", False),
        ("ctx_constructions_ponctuelles", "Constructions ponctuelles (calvaires, antennes, silos…)",
         _T + "construction_ponctuelle", "point", "nature", "", False),
        ("ctx_terrains_sport", "Terrains de sport", _T + "terrain_de_sport", "surface", "nature", "", False),
        ("zones_activite", "Zones d'activité ou d'intérêt (carrières, usines, campings…)",
         _T + "zone_d_activite_ou_d_interet", "surface", "nature", "", False),
    )),
    ("Hydrographie", "#2c7bb6", (
        ("surfaces_en_eau", "Surfaces en eau et mares", _T + "surface_hydrographique", "surface", "nature", "", True),
        ("cours_eau", "Cours d'eau, canaux et fossés", _T + "troncon_hydrographique", "ligne", "nature", "", True),
        ("ctx_plans_eau", "Plans d'eau (étangs, lacs, bassins)", _T + "plan_d_eau", "surface", "nature", "", False),
        ("ctx_details_hydro", "Détails hydrographiques (sources, fontaines, lavoirs)",
         _T + "detail_hydrographique", "point", "nature", "", False),
    )),
    ("Énergie et réseaux", "#7b3294", (
        ("ctx_lignes_electriques", "Lignes électriques", _T + "ligne_electrique", "ligne", "", "", False),
        ("ctx_pylones", "Pylônes", _T + "pylone", "point", "", "", False),
        ("ctx_postes_transformation", "Postes de transformation", _T + "poste_de_transformation", "surface", "", "", False),
        ("ctx_canalisations", "Canalisations", _T + "canalisation", "ligne", "nature", "", False),
    )),
    ("Parcellaire et toponymie", "#636363", (
        ("lieux_dits", "Lieux-dits", _T + "lieu_dit_non_habite", "point", "toponyme", "", False),
    )),
    ("IGN complément", "#c51b7d", (
        ("zones_habitation", "Zones d'habitation", _T + "zone_d_habitation", "surface", "nature", "", True),
        ("ctx_rpg", "Parcelles agricoles (RPG 2024)",
         "IGNF_RPG_PARCELLES-AGRICOLES-CATEGORISEES_2024:parcelles_agricole_categorisees_2024", "surface",
         "cat_cult_p", "", False),
    )),
    # Géorisques (BRGM) : son propre service (``SERVICE_GEORISQUES``), couches préfixées « ms: ».
    ("Géorisques (BRGM)", "#b35806", (
        ("ctx_cavites", "Cavités souterraines", "ms:CAVITE_LOCALISEE", "point", "type_cavite", "", True),
        ("ctx_mouvements_terrain", "Mouvements de terrain (effondrements, glissements…)", "ms:MVT_LOCALISE",
         "point", "", "", True),
        ("ctx_sites_industriels", "Anciens sites industriels (CASIAS)", "ms:SSP_ETS_GE_POINT", "point",
         "nom_etablissement", "", False),
        ("ctx_sols_pollues", "Secteurs d'information sur les sols (pollués)", "ms:SSP_CLASSIF_SIS_GE", "surface",
         "nom_etablissement", "", False),
    )),
    ("Patrimoine", "#b2182b", (
        ("monuments_historiques", "Monuments historiques", "wfs_sup:generateur_sup_s", "surface", "nomsuplitt",
         "\"suptype\" = 'ac1'", True),
    )),
)
PROPRIETE = "archeologia/fond_public"
#: Axe du temps de la frise.
AXE = (1750, 2030)
#: France métropolitaine et Corse (lon/lat) : emprise posée sur un fond national, pour que QGIS ne
#: réclame pas de tuiles au bout du monde (refusées par le serveur, cf. visualisation_tab).
FRANCE = (-5.5, 41.0, 10.0, 51.5)


@dataclass(frozen=True)
class Fond:
    id: str
    couche: str
    titre: str
    epoque: str
    debut: Optional[int]        # None = sans date
    fin: Optional[int]          # None = jusqu'à aujourd'hui
    format: str
    style: str
    zmin: int
    zmax: int
    detail_m: float = 0.0
    repere: bool = False        # transparent : se pose par-dessus un fond
    vignette: str = ""          # relatif au dossier du catalogue
    legende: str = ""           # idem ; vide = pas de légende officielle
    apercu: str = ""            # idem ; l'image de la fiche (plus grande que la vignette)
    lieu_apercu: str = ""       # où l'aperçu a été pris (« Fénétrange, Moselle »)
    source: str = ""
    typename: str = ""          # objets (vecteur WFS) : nom de la couche, ex. « BDTOPO_V3:batiment »
    couleur: str = ""           # objets : couleur du contour
    attribut: str = ""          # objets : champ montré au survol et à l'identification…
    expression: str = ""        # …ou une expression QGIS, prioritaire (références d'une parcelle, libellé d'un code)
    geometrie: str = "surface"  # objets : « surface » (contour), « ligne » ou « point » (étiqueté)
    srs: str = "EPSG:2154"      # objets : système demandé au service (les servitudes ne répondent qu'en 4326)
    filtre: str = ""            # objets : filtre QGIS, appliqué au dessin (les monuments parmi les servitudes)
    service_objets: str = ""    # objets : service vecteur, quand ce n'est pas la Géoplateforme (Géorisques)
    wms: str = ""               # image : adresse d'un service WMS, quand le fond n'est pas une tuile de la Géoplateforme
    theme: str = ""             # titre de sa section dans la page (``THEMES``)
    quoi: str = ""              # objets : ce qu'on y lit, en une phrase (à la place de la frise)
    essai: bool = False         # source à l'essai : ni fiche, ni vignette, ni couverture (essais.json)
    zone: str = ""              # fond local : nom de sa zone…
    emprise: Optional[Tuple[float, float, float, float]] = None   # …et son emprise lon/lat

    @property
    def nom_couche(self) -> str:
        """Nom dans l'arbre des couches : l'époque d'abord, l'arbre se lit comme une frise."""
        return f"{self.epoque} · {self.titre}" if self.epoque else self.titre

    @property
    def local(self) -> bool:
        return self.emprise is not None

    @property
    def affichage(self) -> str:
        """Ce que montrent l'identification et le survol : l'expression, sinon le champ, entre guillemets."""
        return self.expression or (f'"{self.attribut}"' if self.attribut else "")

    @property
    def objets(self) -> bool:
        """Vrai pour un vecteur (bâtiments, surfaces en eau) : des contours cliquables, dessinés en
        contours par-dessus le relief, et non une image."""
        return bool(self.typename)



#: Sources à l'essai (2026-11-12) : même forme que le catalogue, sans fiche, vignette ni couverture.
ESSAIS = CATALOGUE.parent / "essais.json"


def charger_essais(chemin: Path) -> List[Fond]:
    """Les sources à l'essai, marquées ``essai`` ; fichier absent ou illisible → aucune."""
    try:
        return [replace(f, essai=True) for f in charger(chemin)[1]]
    except (OSError, ValueError):
        return []


#: Thèmes de la page, dans l'ordre affiché (2026-11-12) : les images d'abord, puis les données vectorielles.
THEMES = ("Cartes anciennes", "Photos aériennes", "Relief, sol et géologie", "Archéologie connue et patrimoine",
          "Bâti, routes et eau", "Relief, sous-sol et mines", "Aménagements modernes")


def par_theme(fonds: Sequence[Fond]) -> List[Tuple[str, bool, List[Fond]]]:
    """``[(thème, objets, fonds), …]`` : une section par thème et par sorte, images avant vecteurs, thèmes dans
    l'ordre de ``THEMES`` (un thème inconnu passe à la fin). Dans une section d'images, l'ordre est celui du
    temps, les sans-date à la fin ; dans une section de vecteurs, celui reçu (le catalogue avant les essais)."""
    rang = {t: i for i, t in enumerate(THEMES)}
    groupes: Dict[Tuple[bool, int, str], List[Fond]] = {}
    for f in fonds:
        groupes.setdefault((f.objets, rang.get(f.theme, len(THEMES)), f.theme), []).append(f)
    out = []
    for (objets, _r, theme), membres in sorted(groupes.items(), key=lambda kv: kv[0]):
        if not objets:
            membres = sorted(membres, key=lambda f: (f.debut is None, f.debut or 0, f.fin or 9999))
        out.append((theme, objets, membres))
    return out


def texte_recherche(fond: Fond) -> str:
    """Ce dans quoi la recherche de la page cherche, en minuscules : titre, époque, provenance, zone, phrase."""
    return " ".join((fond.titre, fond.epoque, fond.source, fond.zone, fond.quoi, fond.theme)).lower()


def couvre(fond: Fond, emprise: Optional[Tuple[float, float, float, float]]) -> bool:
    """Vrai si le fond a quelque chose à montrer dans ``emprise`` (lon/lat de la carte affichée) : toujours
    pour un fond national, ou quand la carte n'est pas connue ; pour un fond local, si les deux se touchent."""
    if emprise is None or fond.emprise is None:
        return True
    x0, y0, x1, y1 = fond.emprise
    return not (emprise[2] < x0 or emprise[0] > x1 or emprise[3] < y0 or emprise[1] > y1)


def charger(chemin: Path) -> Tuple[str, List[Fond]]:
    """``(service, fonds)`` ; une entrée incomplète est ignorée plutôt que de vider la page."""
    brut = json.loads(Path(chemin).read_text(encoding="utf-8"))
    fonds = []
    for f in brut.get("fonds") or []:
        try:
            emprise = f.get("emprise")
            fonds.append(Fond(
                id=str(f["id"]), couche=str(f["couche"]), titre=str(f["titre"]), epoque=str(f["epoque"]),
                debut=f.get("debut"), fin=f.get("fin"), format=str(f["format"]), style=str(f["style"]),
                zmin=int(f["zmin"]), zmax=int(f["zmax"]), detail_m=float(f.get("detail_m") or 0),
                repere=bool(f.get("repere")), vignette=str(f.get("vignette") or ""),
                legende=str(f.get("legende") or ""), apercu=str(f.get("apercu") or ""),
                typename=str(f.get("typename") or ""), couleur=str(f.get("couleur") or ""),
                attribut=str(f.get("attribut") or ""), expression=str(f.get("expression") or ""),
                geometrie=str(f.get("geometrie") or "surface"), srs=str(f.get("srs") or "EPSG:2154"),
                filtre=str(f.get("filtre") or ""), service_objets=str(f.get("service_objets") or ""),
                wms=str(f.get("wms") or ""), theme=str(f.get("theme") or ""), quoi=str(f.get("quoi") or ""),
                lieu_apercu=str(f.get("lieu_apercu") or ""),
                source=str(f.get("source") or ""), zone=str(f.get("zone") or ""),
                emprise=tuple(float(v) for v in emprise) if emprise and len(emprise) == 4 else None))
        except (KeyError, TypeError, ValueError):
            continue
    return str(brut.get("service") or ""), fonds


def _gabarit(service: str, fond: Fond) -> str:
    return (f"{service}?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER={fond.couche}&STYLE={fond.style}"
            f"&FORMAT={fond.format}&TILEMATRIXSET=PM")


def uri_couche(service: str, fond: Fond) -> str:
    """URI du fournisseur ``wms`` de QGIS, en tuiles directes (``type=xyz``).

    La grille « PM » de la Géoplateforme est la grille Web Mercator standard : pas besoin du
    GetCapabilities (3 Mo) à chaque ouverture. ⚠ Seuls ``&`` et ``=`` de l'adresse sont encodés :
    QGIS 3.44 (Qt5) ne décode pas une adresse encodée en entier et ne reçoit alors aucune tuile,
    sans erreur (mesuré le 2026-11-11 ; QGIS 4 accepte les deux formes).
    """
    if fond.wms:
        # Service WMS d'un autre producteur (BRGM, DataGrandEst…) : une image par vue, en Web Mercator.
        return (f"contextualWMSLegend=0&crs=EPSG:3857&dpiMode=7&format={fond.format}&layers={fond.couche}"
                f"&styles=&url={fond.wms}")
    adresse = _gabarit(service, fond) + "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"
    adresse = adresse.replace("&", "%26").replace("=", "%3D")
    return f"type=xyz&url={adresse}&zmin={fond.zmin}&zmax={fond.zmax}"


#: Service vecteur de la Géoplateforme, et échelle au-delà de laquelle un vecteur ne se charge pas :
#: QGIS ne demande que les objets de la zone affichée, mais un département de bâtiments se compte
#: en centaines de milliers d'objets.
SERVICE_OBJETS = "https://data.geopf.fr/wfs/ows"
#: Service vecteur de Géorisques (BRGM) : cavités, mouvements de terrain, sites industriels, sols pollués.
SERVICE_GEORISQUES = "https://www.georisques.gouv.fr/services"
ECHELLE_MIN_OBJETS = 25000


def uri_objets(fond: Fond, service: str = SERVICE_OBJETS, version: str = "2.0.0") -> str:
    """URI du fournisseur ``WFS`` de QGIS : chargement **en direct**, limité à l'emprise affichée
    (``restrictToRequestBBOX``) et paginé. Vérifié sous QGIS 3.44 et 4.0.3 le 2026-11-11."""
    return (f"pagingEnabled='true' restrictToRequestBBOX='1' srsname='{fond.srs}' "
            f"typename='{fond.typename}' url='{fond.service_objets or service}' version='{version}'")


def couches_contexte(catalogue: Sequence[Fond] = ()) -> List[Tuple[str, Fond, bool]]:
    """``[(famille, fond, cochée), …]`` du bouton « Ajouter le contexte moderne », dans l'ordre de l'arbre.
    Une couche déjà au catalogue garde son expression de clic et son système ; toutes prennent la couleur
    de leur famille et un nom sans époque."""
    par_id = {f.id: f for f in catalogue}
    out = []
    for famille, couleur, couches in CONTEXTE_MODERNE:
        for ident, titre, typename, geometrie, attribut, filtre, cochee in couches:
            connu = par_id.get(ident)
            if connu is not None:
                fond = replace(connu, titre=titre, epoque="", couleur=couleur, legende="")
            else:
                fond = Fond(id=ident, couche=typename, titre=titre, epoque="", debut=None, fin=None, format="",
                            style="", zmin=0, zmax=19, typename=typename, couleur=couleur, attribut=attribut,
                            geometrie=geometrie, filtre=filtre,
                            service_objets=SERVICE_GEORISQUES if typename.startswith("ms:") else "",
                            srs="EPSG:4326" if typename.startswith("wfs_sup:") else "EPSG:2154")
            out.append((famille, fond, cochee))
    return out


def position(fond: Fond, axe: Tuple[int, int] = AXE) -> Optional[Tuple[float, float]]:
    """``(début, fin)`` de la barre sur la frise, en fractions de l'axe ; ``None`` = sans date."""
    if fond.debut is None:
        return None
    a0, a1 = axe
    fin = a1 if fond.fin is None else fond.fin
    d = (fond.debut - a0) / (a1 - a0)
    f = (fin - a0) / (a1 - a0)
    return max(0.0, min(1.0, d)), max(0.0, min(1.0, max(f, d)))


def emprise_3857(fond: Fond) -> Tuple[float, float, float, float]:
    """Emprise de la couche en Web Mercator (le SCR d'une couche ``xyz``)."""
    x0, y0, x1, y1 = fond.emprise or FRANCE
    r = 6378137.0

    def m(lon: float, lat: float) -> Tuple[float, float]:
        return math.radians(lon) * r, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * r

    (a, b), (c, d) = m(x0, y0), m(x1, y1)
    return a, b, c, d


def resume_ajout(ajoutes: int, deja: int, indisponibles: int = 0) -> str:
    """Phrase d'état après « Ajouter » : rien ne change sur la carte, il faut le dire. ``indisponibles`` :
    fonds cochés dont le service n'a pas répondu (2026-11-18 : ils disparaissaient sans un mot)."""
    manque = ""
    if indisponibles:
        s = "s" if indisponibles > 1 else ""
        manque = (f"{indisponibles} fond{s} indisponible{s} : {'leur' if s else 'son'} service ne répond pas "
                  f"ou ne {'les' if s else 'le'} publie plus. Réessayez plus tard.")
    if ajoutes == 0:
        if manque:
            return manque
        return ("Ces fonds sont déjà dans le projet." if deja else "Aucun fond coché.")
    pluriel = "s" if ajoutes > 1 else ""
    phrase = (f"{ajoutes} fond{pluriel} ajouté{pluriel} dans QGIS, décoché{pluriel} : cochez-en un dans le groupe "
              f"« {GROUPE_FONDS} » de l'arbre des couches. Un seul s'affiche à la fois.")
    return f"{phrase} {manque}" if manque else phrase


# ----------------------------------------------------------------------
# Couverture réelle d'un fond sur la France (carte de sa fiche)
# ----------------------------------------------------------------------
COUVERTURE = CATALOGUE.parent / "couverture.json"


def bornes_case(zoom: int, x: int, y: int) -> Tuple[float, float, float, float]:
    """``(lon ouest, lat sud, lon est, lat nord)`` d'une case de la grille Web Mercator."""
    n = 2 ** zoom

    def lat(rang: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * rang / n))))

    return x / n * 360.0 - 180.0, lat(y + 1), (x + 1) / n * 360.0 - 180.0, lat(y)


def centre_case(zoom: int, x: int, y: int) -> Tuple[float, float]:
    ouest, sud, est, nord = bornes_case(zoom, x, y)
    return (ouest + est) / 2, (sud + nord) / 2


@dataclass(frozen=True)
class Couverture:
    """Les cases de la grille où le fond a une image (mesuré par ``dev/fonds_couverture.py``)."""
    zoom: int
    cases: Tuple[Tuple[int, int], ...]      # (colonne, rangée) couvertes
    part: float                              # part des cases de France couvertes, 0 à 1

    @property
    def phrase(self) -> str:
        """Ce que dit la carte, en mots : jamais « 100 % » pour 99,6 %, jamais « 0 % » pour un fond local."""
        if self.part >= 0.995:
            return "Toute la France métropolitaine"
        pourcent = round(self.part * 100)
        if pourcent < 1:
            return "Moins de 1 % de la France métropolitaine"
        return f"Environ {pourcent} % de la France métropolitaine"


def charger_couvertures(chemin: Path) -> dict:
    """``id de fond → Couverture`` ; ``{}`` si le fichier manque ou est illisible (la fiche s'en passe)."""
    try:
        brut = json.loads(Path(chemin).read_text(encoding="utf-8"))
        zoom, x0, y0, total = int(brut["zoom"]), int(brut["x0"]), int(brut["y0"]), int(brut["cases_france"])
        out = {}
        for ident, bloc in (brut.get("fonds") or {}).items():
            cases = tuple((x0 + i, y0 + j) for j, ligne in enumerate(bloc.get("lignes") or [])
                          for i, c in enumerate(ligne) if c == "1")
            out[str(ident)] = Couverture(zoom, cases, len(cases) / total if total else 0.0)
        return out
    except (OSError, ValueError, KeyError, TypeError):
        return {}


# ----------------------------------------------------------------------
# Fiche d'un fond (ce qui s'écrit à la main, avec ses sources)
# ----------------------------------------------------------------------
FICHES = CATALOGUE.parent / "fiches.json"
#: Blocs qu'une fiche livrée doit porter (même exigence que les fiches des produits).
BLOCS_FICHE = ("resume", "lire", "usage", "limites", "origine", "references")


@dataclass(frozen=True)
class Reference:
    """Une source. ``citation`` est obligatoire, l'``url`` est un confort."""
    citation: str
    url: str = ""


@dataclass(frozen=True)
class FicheFond:
    """Ce qu'on lit d'un fond avant de l'ajouter. L'identité (titre, époque, source, couche) reste
    dans le catalogue : ce fichier ne porte que ce qui s'écrit à la main. Tout est optionnel."""
    resume: str = ""
    lire: str = ""
    usage: Tuple[str, ...] = ()
    limites: Tuple[str, ...] = ()
    origine: Tuple[str, ...] = ()
    references: Tuple[Reference, ...] = ()

    @property
    def manques(self) -> Tuple[str, ...]:
        return tuple(b for b in BLOCS_FICHE if not getattr(self, b))

    @property
    def est_complete(self) -> bool:
        return not self.manques


def _textes(valeur) -> Tuple[str, ...]:
    if isinstance(valeur, str):
        valeur = [valeur]
    return tuple(str(t).strip() for t in (valeur or []) if str(t).strip())


def charger_fiches(chemin: Path) -> dict:
    """``id de fond → FicheFond`` ; ``{}`` si le fichier manque ou est illisible. Les clés préfixées
    ``_`` (mode d'emploi du fichier) sont ignorées."""
    try:
        brut = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for ident, f in (brut.items() if isinstance(brut, dict) else []):
        if ident.startswith("_") or not isinstance(f, dict):
            continue
        refs = tuple(Reference(str(r.get("citation") or "").strip(), str(r.get("url") or "").strip())
                     for r in (f.get("references") or []) if isinstance(r, dict) and r.get("citation"))
        out[ident] = FicheFond(resume=str(f.get("resume") or "").strip(), lire=str(f.get("lire") or "").strip(),
                               usage=_textes(f.get("usage")), limites=_textes(f.get("limites")),
                               origine=_textes(f.get("origine")), references=refs)
    return out
