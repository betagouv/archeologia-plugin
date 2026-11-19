"""Chargement des couches résultat dans le projet QGIS (raster VRT + vecteurs).

Porté depuis ``main_dialog._load_layers_to_project`` pour être partagé par la
V2 (``run_view``). Fonctions QGIS-side : ne pas importer hors QGIS.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from ..app.progress_reporter import USER_INFO
from ..app.services.nom_analyse import (
    GROUPE_INDICES,
    PROPRIETE,
    est_qualite,
    groupe_analyse,
    groupe_indices,
    groupe_qualite,
    groupe_structures,
    indice_coche,
    retirer_groupes_vides,
)
from ..app.services.vocabulaire import titre_dossier_image


def _apply_cluster_style(layer, logger: logging.Logger) -> None:
    """Hachures croisées noires + contour : style des zones de clustering."""
    try:
        from qgis.core import (
            QgsFillSymbol,
            QgsLinePatternFillSymbolLayer,
            QgsSimpleLineSymbolLayer,
            QgsSingleSymbolRenderer,
        )
        from qgis.PyQt.QtGui import QColor

        symbol = QgsFillSymbol()
        symbol.deleteSymbolLayer(0)
        for angle in (45, 135):
            hatch = QgsLinePatternFillSymbolLayer()
            hatch.setLineAngle(angle)
            hatch.setDistance(3.0)
            hatch.setLineWidth(0.4)
            hatch.setColor(QColor(0, 0, 0))
            symbol.appendSymbolLayer(hatch)
        outline = QgsSimpleLineSymbolLayer()
        outline.setColor(QColor(0, 0, 0))
        outline.setWidth(0.6)
        symbol.appendSymbolLayer(outline)
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.triggerRepaint()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Impossible d'appliquer le style cluster: {e}")


def _apply_confidence_style(
    layer, base_color, confidence_threshold: float, logger: logging.Logger,
) -> None:
    """Symbologie catégorisée par tranche de confiance (contour coloré).

    ``base_color`` est la couleur de base RGB de la classe (registre) ; chaque
    tranche de confiance la décline en luminosité via ``apply_confidence``.
    """
    try:
        from qgis.core import (
            QgsCategorizedSymbolRenderer,
            QgsFillSymbol,
            QgsRendererCategory,
        )

        from ..pipeline.cv.class_utils import compute_confidence_bins
        from ..pipeline.cv.color_palette import apply_confidence

        bins = compute_confidence_bins(max(0.0, float(confidence_threshold or 0.0)))
        categories = []
        for b in bins:
            r, g, bl = apply_confidence(base_color, b["repr"])
            symbol = QgsFillSymbol.createSimple({
                "color": "0,0,0,0",
                "outline_color": f"{r},{g},{bl},255",
                "outline_width": "0.6",
                "outline_style": "solid",
            })
            categories.append(QgsRendererCategory(b["label"], symbol, b["label"]))
        if not categories:
            return
        layer.setRenderer(QgsCategorizedSymbolRenderer("conf_bin", categories))
        layer.triggerRepaint()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Impossible d'appliquer le style: {e}")


def _fiabilite_symbol(base_color, spec):
    """Symbole d'une catégorie de fiabilité = le rendu d'origine des tranches de
    confiance : contour seul (aucun remplissage, la structure détectée reste
    lisible), dans la couleur de la classe déclinée en luminosité par
    ``apply_confidence`` (plus sombre = plus sûr). Même couleur de base pour une
    classe quel que soit le run (registre), même déclinaison pour tous les modèles."""
    from qgis.core import QgsFillSymbol

    from ..pipeline.cv.color_palette import apply_confidence

    r, g, b = apply_confidence(base_color, float(spec["repr"]))
    return QgsFillSymbol.createSimple({
        "color": "0,0,0,0",
        "outline_color": f"{r},{g},{b},255",
        "outline_width": str(spec["outline_width"]),
        "outline_style": "solid",
    })


def _apply_fiabilite_style(layer, base_color, cats, logger: logging.Logger, classe: str = "") -> None:
    """Symbologie catégorisée sur ``fiabilite`` (2026-09-09) : contour seul dans la
    couleur de la classe, déclinée en luminosité par catégorie — exactement le
    rendu historique de ``_apply_confidence_style``, avec les catégories de
    fiabilité à la place des tranches de score (``app.services.fiabilite.STYLE_SPEC``).
    Libellés de légende = niveau garanti (« Probable · ≥ 60 % de vrais »),
    catégorie la plus sûre en tête. Les niveaux « possible » et « douteux » sont
    présents mais décochés à l'ouverture (``fiabilite.visible_par_defaut``, sauf exception
    de la ``classe`` : « possible » coché pour les parcellaires, 2026-11-10) : l'état
    est enregistré dans le projet .qgs comme dans la couche chargée en direct."""
    try:
        from qgis.core import QgsCategorizedSymbolRenderer, QgsRendererCategory

        from ..app.services.fiabilite import CHAMP_LABEL, STYLE_SPEC, labels_legende, visible_par_defaut

        labels = labels_legende(cats)
        categories = []
        for c in sorted(cats, key=lambda x: x.seuil, reverse=True):
            symbol = _fiabilite_symbol(base_color, STYLE_SPEC[c.categorie])
            categorie = QgsRendererCategory(c.label, symbol, labels.get(c.categorie, c.label))
            categorie.setRenderState(visible_par_defaut(c.categorie, classe))
            categories.append(categorie)
        if not categories:
            return
        layer.setRenderer(QgsCategorizedSymbolRenderer(CHAMP_LABEL, categories))
        layer.triggerRepaint()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Impossible d'appliquer le style fiabilité: {e}")


def _apply_fiabilite_notices(layer, entree, cats, logger: logging.Logger) -> None:
    """Résumé de couche (infobulle du panneau des couches + métadonnées) et
    infobulle de détection (map tip) : là où la phrase « ≥ 85 % de vrais objets sur
    le banc (mesuré : 95 % sur 1 013 détections) » a la place d'exister."""
    from ..app.services.fiabilite import maptip_html, texte_resume

    modele = str(entree.get("modele") or "")
    # Libellé de la couche (« Charbonnières »), jamais l'identifiant de classe (2026-11-18).
    resume = texte_resume(modele, layer.name() or str(entree.get("classe") or ""), cats,
                          str(entree.get("provenance") or ""))
    try:
        md = layer.metadata()
        md.setAbstract(resume)
        layer.setMetadata(md)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Métadonnées de couche non écrites: {e}")
    try:
        # QGIS ≥ 3.38 : serverProperties() ; avant : setAbstract() sur la couche.
        sp = layer.serverProperties() if hasattr(layer, "serverProperties") else None
        if sp is not None and hasattr(sp, "setAbstract"):
            sp.setAbstract(resume)
        elif hasattr(layer, "setAbstract"):
            layer.setAbstract(resume)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Résumé de couche non écrit: {e}")
    try:
        layer.setMapTipTemplate(maptip_html(cats, modele, structure=layer.name()))
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Infobulle de détection non écrite: {e}")


def _fiabilite_for_source(ogr_source: str, layer):
    """``(entrée sidecar, catégories)`` si la couche porte le champ ``fiabilite`` ET
    que ``fiabilite.json`` (à côté du GeoPackage) la décrit ; sinon ``(None, ())``."""
    from ..app.services.fiabilite import CHAMP_LABEL, categories_sidecar, read_sidecar

    try:
        if layer.fields().indexFromName(CHAMP_LABEL) < 0:
            return None, ()
        gpkg, layer_name, _ = _parse_gpkg_source(str(ogr_source))
        entree = read_sidecar(gpkg, layer_name)
        cats = categories_sidecar(entree)
        return (entree, cats) if cats else (None, ())
    except Exception:  # noqa: BLE001
        return None, ()


def _parse_gpkg_source(shp_path_str: str):
    """``(gpkg_path, layer_name, class_name)`` depuis ``path.gpkg|layername=X`` ou ``path.shp``.

    Pour un GPKG, ``layer_name`` = ``class_name`` = la table. Pour un shapefile legacy
    ``detections_<RVT>_<classe>``, ``class_name`` est extrait du stem.
    """
    if "|layername=" in shp_path_str:
        _gpkg, layer_name = shp_path_str.split("|layername=", 1)
        class_name = layer_name
    else:
        _gpkg = shp_path_str
        layer_name = Path(shp_path_str).stem
        parts = layer_name.split("_")
        class_name = (
            "_".join(parts[2:])
            if len(parts) >= 3 and parts[0] == "detections"
            else layer_name
        )
    return _gpkg, layer_name, class_name


def _ajouter_contexte_moderne(layer, logger) -> None:
    """Catégorie grise « Contexte moderne » (2026-11-11) : le rendu catégorisé déjà posé (fiabilité
    ou tranches de confiance) passe sur une expression qui renvoie « Contexte moderne » quand le champ
    ``contexte_moderne`` est rempli, sinon la valeur d'origine. Le champ ``fiabilite`` n'est jamais
    réécrit : bilan, rapport et fiabilité observée en dépendent. Couche sans le champ (traitement
    antérieur, option coupée) : rien ne change, une expression sur un champ absent masquerait tout."""
    try:
        from qgis.core import QgsCategorizedSymbolRenderer, QgsFillSymbol, QgsRendererCategory

        from ..app.services.contexte_moderne import (
            CATEGORIE_LEGENDE, CHAMPS_ECART, COULEUR_LEGENDE, est_lineaire, expression_legende,
        )

        champs = tuple(c for c in CHAMPS_ECART if layer.fields().indexFromName(c) >= 0)
        if not champs:
            return
        # Sans le modèle d'une comparaison A/B (« Charbonnières — Structures linéaires… », 2026-11-18).
        if est_lineaire(layer.name().split(" — ")[0]):
            # jamais écartée par le contexte moderne ; seulement par une aire minimale réglée
            champs = tuple(c for c in champs if c != "contexte_moderne")
            if not champs:
                return
        renderer = layer.renderer()
        if not isinstance(renderer, QgsCategorizedSymbolRenderer):
            return
        if any(c.value() == CATEGORIE_LEGENDE for c in renderer.categories()):
            return
        renderer.setClassAttribute(expression_legende(renderer.classAttribute(), champs))
        symbole = QgsFillSymbol.createSimple({"color": "0,0,0,0", "outline_color": COULEUR_LEGENDE,
                                              "outline_width": "0.5", "outline_style": "dash"})
        categorie = QgsRendererCategory(CATEGORIE_LEGENDE, symbole, CATEGORIE_LEGENDE)
        categorie.setRenderState(False)   # décochée à l'ouverture, comme « possible » et « douteux »
        renderer.addCategory(categorie)
        layer.triggerRepaint()
    except Exception as e:  # noqa: BLE001 — la légende d'origine reste
        logger.warning(f"Catégorie « Écartées » non ajoutée : {e}")


def build_detection_vector_layer(
    ogr_source: str,
    layer_name: str,
    *,
    base_color,
    confidence_threshold: float,
    logger: logging.Logger,
):
    """Construit un ``QgsVectorLayer`` de détection valide, CRS fixé + symbologie appliquée.

    ``base_color`` : couleur de base RGB de la classe (résolue via le registre par
    l'appelant). Symbologie : zone de synthèse (hachures) si un champ de comptage
    de brique est présent (``nb_detect``/``nb_sources`` — cf.
    ``app.services.detection_symbology``, les sorties de synthèse n'ont pas de
    ``conf_bin`` exploitable) ; sinon catégorisée par **fiabilité** (champ
    ``fiabilite`` + sidecar ``fiabilite.json``, style D dans la teinte de l'entité,
    résumé de couche et infobulle de détection) ; sinon par tranche de confiance.
    **N'ajoute la couche à AUCUN projet** — l'appelant en est propriétaire.
    Source unique de vérité partagée par le chargement live
    (:func:`load_result_layers`) ET l'écriture du projet ``.qgs``
    (``ui/qgs_writer.py``). ``None`` si la couche est invalide.
    """
    from qgis.core import QgsVectorLayer

    from ..app.services.detection_symbology import is_synthesis_layer

    layer = QgsVectorLayer(ogr_source, layer_name, "ogr")
    if not layer.isValid():
        return None
    # Couche de détection vide (0 entité, p.ex. vidée par le filtre d'aire) : ne pas
    # la charger (évite l'avertissement « CRS absent » sur une couche sans donnée).
    # featureCount() == -1 = inconnu → on conserve (prudence).
    if layer.featureCount() == 0:
        logger.info(f"Couche détection vide ignorée: {layer_name}")
        return None
    _ensure_layer_crs(layer, logger)
    if is_synthesis_layer(f.name() for f in layer.fields()):
        _apply_cluster_style(layer, logger)
    else:
        # Fiabilité (catégories par classe, 2026-09-09) si la couche et son sidecar
        # la portent ; sinon tranches de confiance historiques (conf_bin).
        entree, cats = _fiabilite_for_source(ogr_source, layer)
        if cats:
            _apply_fiabilite_style(layer, base_color, cats, logger,
                                   classe=str((entree or {}).get("classe") or ""))
            _apply_fiabilite_notices(layer, entree, cats, logger)
        else:
            _apply_confidence_style(layer, base_color, confidence_threshold, logger)
    _ajouter_contexte_moderne(layer, logger)
    _apply_verdict_form(layer)
    return layer


def _apply_verdict_form(layer) -> None:
    """Le champ « validation » propose le vocabulaire FIXE des verdicts (oui / non /
    peut-être) aussi sur les couches chargées en direct, pas seulement dans le .qgs :
    c'est ce que lit la fiabilité observée (``app.services.fiabilite_observee``)."""
    try:
        from qgis.core import QgsEditorWidgetSetup

        i = layer.fields().indexFromName("validation")
        if i >= 0:
            layer.setEditorWidgetSetup(i, QgsEditorWidgetSetup(
                "ValueMap", {"map": [{"oui": "oui"}, {"non": "non"}, {"peut-être": "peut-être"}]},
            ))
    except Exception:  # noqa: BLE001 — confort de saisie, jamais bloquant
        pass


def apply_coverage_raster_symbology(layer, threshold_percent: float, logger: logging.Logger) -> None:
    """Pseudo-couleur du raster COUVERTURE : 0 % rouge opaque → seuil orange
    semi-transparent → 100 % entièrement transparent. Les lacunes « brillent »
    par-dessus le MNT, le reste s'efface. Partagée chargement live / ``.qgs``."""
    try:
        from qgis.core import (
            QgsColorRampShader,
            QgsRasterShader,
            QgsSingleBandPseudoColorRenderer,
        )
        from qgis.PyQt.QtGui import QColor

        thr = float(threshold_percent)
        items = [
            QgsColorRampShader.ColorRampItem(0.0, QColor(178, 24, 43, 255), "0 % (pas de points sol)"),
            QgsColorRampShader.ColorRampItem(thr, QColor(244, 165, 130, 180), f"{thr:.0f} % (seuil)"),
            QgsColorRampShader.ColorRampItem(100.0, QColor(255, 255, 255, 0), "100 % (bien couvert)"),
        ]
        shader_fn = QgsColorRampShader(0.0, 100.0)
        shader_fn.setColorRampType(QgsColorRampShader.Type.Interpolated)
        shader_fn.setClassificationMode(QgsColorRampShader.ClassificationMode.Continuous)
        shader_fn.setColorRampItemList(items)
        shader = QgsRasterShader()
        shader.setRasterShaderFunction(shader_fn)
        renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
        renderer.setClassificationMin(0.0)
        renderer.setClassificationMax(100.0)
        layer.setRenderer(renderer)
        layer.triggerRepaint()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Symbologie couverture non appliquée: {e}")


def low_coverage_layer_display_name(threshold_percent: float) -> str:
    """Nom d'affichage de la couche QA (partagé live / .qgs / réutilisation)."""
    return f"Zones mal couvertes (<{float(threshold_percent):.0f} %)"


def build_low_coverage_vector_layer(gpkg_path: str, threshold_percent: float, logger: logging.Logger):
    """Couche « Zones mal couvertes » stylée (hachures rouges 45°/135° + contour
    rouge, intérieur transparent), CRS fixé. N'ajoute la couche à AUCUN projet —
    l'appelant en est propriétaire. Partagée chargement live / ``.qgs``.
    ``None`` si invalide."""
    try:
        from qgis.core import (
            QgsFillSymbol,
            QgsLinePatternFillSymbolLayer,
            QgsSimpleLineSymbolLayer,
            QgsSingleSymbolRenderer,
            QgsVectorLayer,
        )
        from qgis.PyQt.QtGui import QColor

        from ..pipeline.coverage_polygons import GPKG_LAYER_NAME

        name = low_coverage_layer_display_name(threshold_percent)
        layer = QgsVectorLayer(f"{gpkg_path}|layername={GPKG_LAYER_NAME}", name, "ogr")
        if not layer.isValid():
            # Repli : GPKG mono-couche sans nom de couche connu.
            layer = QgsVectorLayer(str(gpkg_path), name, "ogr")
            if not layer.isValid():
                return None
        _ensure_layer_crs(layer, logger)
        red = QColor(200, 30, 30)
        symbol = QgsFillSymbol()
        symbol.deleteSymbolLayer(0)
        for angle in (45, 135):
            hatch = QgsLinePatternFillSymbolLayer()
            hatch.setLineAngle(angle)
            hatch.setDistance(3.0)
            hatch.setLineWidth(0.4)
            hatch.setColor(red)
            symbol.appendSymbolLayer(hatch)
        outline = QgsSimpleLineSymbolLayer()
        outline.setColor(red)
        outline.setWidth(0.6)
        symbol.appendSymbolLayer(outline)
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.triggerRepaint()
        return layer
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Couche zones mal couvertes non construite: {e}")
        return None


def load_result_layers(
    vrt_paths: list,
    shapefile_paths: list,
    class_colors: Optional[list],
    logger: logging.Logger,
    confidence_threshold: float = 0.0,
    entity_labels: Optional[dict] = None,
    derived_slugs: Optional[set] = None,
    min_conf_by_slug: Optional[dict] = None,
    qa_paths: Optional[list] = None,
    coverage_threshold_percent: float = 30.0,
    titre_analyse: str = "",
) -> None:
    """Charge les VRT (raster) et vecteurs (détections) dans le projet QGIS,
    applique la symbologie, puis zoome sur l'étendue combinée (déféré).

    Tout va sous le groupe de l'analyse ``titre_analyse`` (« <nom> — JJ/MM/AAAA HH:MM »,
    ``nom_analyse.titre_du_livrable``, 0.19.0) : « Qualité de la donnée » (couche QA en tête, puis
    densité et couverture décochées), « Structures », puis « Indices » (groupe exclusif, LD coché,
    MNT en dernier ; 2026-11-18) ; deux analyses = deux groupes, recharger la même réutilise son
    groupe et ses couches (``_reuse_existing``, rangées dans le bon groupe). Sans titre : arbre à plat d'avant.
    Toutes les couches de détection vont sous le groupe « Structures » (N-02, 2026-10-25) ;
    ``derived_slugs`` (slugs d'entités dérivées ou comparées) + ``entity_labels``
    (slug→libellé) y font un **sous-groupe** par libellé (zone + constituants ensemble,
    « Regroupement de cratères » ; variantes d'une comparaison). Les mosaïques portent le
    nom de l'image (``titre_dossier_image``). Miroir de ``ui/qgs_writer.write_validation_project``."""
    try:
        from qgis.core import (
            QgsProject,
            QgsRasterLayer,
            QgsRectangle,
        )

        from ..pipeline.cv.class_color_registry import color_for_class

        project = QgsProject.instance()
        root = project.layerTreeRoot()
        derived_slugs = derived_slugs or set()
        entity_labels = entity_labels or {}
        min_conf_by_slug = min_conf_by_slug or {}
        loaded_count = 0
        combined_extent = QgsRectangle()
        loaded_layers: List = []
        # ``class_colors`` n'est plus consulté (la couleur dérive du nom de classe
        # via le registre) ; le paramètre est conservé pour ne pas casser les
        # appelants existants.

        # ── Rasters (VRT d'indices) ── MNT en dernier = en bas du groupe, comme dans le .qgs.
        for vrt_path in sorted((v for v in vrt_paths if v), key=lambda v: _rvt_type_of(v).upper() == "MNT"):
            vrt_path_str = str(vrt_path)
            rvt_type = _rvt_type_of(vrt_path_str)
            layer_name = titre_dossier_image(rvt_type)   # « SVF · Creux & dépressions · R10_… » (N-03)

            # Densité et couverture : « Qualité de la donnée », décochées (2026-11-18) ; le reste : « Indices ».
            qualite = est_qualite(rvt_type)
            parent = groupe_analyse(root, titre_analyse)
            cible = groupe_qualite(parent) if qualite else groupe_indices(parent)
            existante = _reuse_existing(project, layer_name, vrt_path_str, loaded_layers, combined_extent)
            if existante:
                # chargée avant cette version : rangée, jamais en double
                _ranger(root, existante, cible, decochee=qualite)
                logger.info(f"Couche raster déjà présente: {layer_name}")
                continue

            layer = QgsRasterLayer(vrt_path_str, layer_name, "gdal")
            if layer.isValid():
                _ensure_layer_crs(layer, logger)
                if rvt_type == "COUVERTURE":
                    apply_coverage_raster_symbology(layer, coverage_threshold_percent, logger)
                project.addMapLayer(layer, False)
                noeud = cible.addLayer(layer)
                if qualite and noeud is not None:
                    noeud.setItemVisibilityChecked(False)
                loaded_layers.append(layer)
                combined_extent = _combine(combined_extent, layer.extent())
                loaded_count += 1
                logger.info(f"Couche raster chargée: {layer_name}")
            else:
                logger.warning(f"Impossible de charger le VRT: {vrt_path_str}")

        # ── Vecteurs (détections : shapefile ou GPKG) ──
        for shp_path in shapefile_paths:
            if not shp_path:
                continue
            shp_path_str = str(shp_path)
            _gpkg, layer_name, class_name = _parse_gpkg_source(shp_path_str)
            ogr_source = shp_path_str
            # slug d'entité = dossier du GeoPackage (detections/<slug>/<slug>.gpkg)
            slug = Path(_gpkg).parent.name

            base_color = color_for_class(class_name)

            if _reuse_existing(project, layer_name, ogr_source, loaded_layers, combined_extent):
                logger.info(f"Couche vecteur déjà présente: {layer_name}")
                continue

            # Seuil par entité (= seuil du run qui a binné conf_bin) ; repli sur le
            # seuil global pour un slug absent de la map (run legacy / sécurité).
            layer_conf = min_conf_by_slug.get(slug, confidence_threshold)
            layer = build_detection_vector_layer(
                ogr_source, layer_name, base_color=base_color,
                confidence_threshold=layer_conf, logger=logger,
            )
            if layer is not None:
                # Toutes les détections sous « Structures » (en haut du groupe de l'analyse,
                # au-dessus des mosaïques) ; une entité dérivée ou comparée y a son
                # sous-groupe (zone + constituants ensemble). Même arbre que le .qgs.
                project.addMapLayer(layer, False)  # pas à la racine
                sous = entity_labels.get(slug, slug) if slug in derived_slugs else ""
                groupe_structures(groupe_analyse(root, titre_analyse), sous).addLayer(layer)
                loaded_layers.append(layer)
                combined_extent = _combine(combined_extent, layer.extent())
                loaded_count += 1
                logger.info(
                    f"Couche vecteur chargée: {layer_name} "
                    f"(classe={class_name}, RGB{base_color})"
                )
            else:
                logger.warning(f"Impossible de charger la couche: {ogr_source}")

        # ── Vecteur QA : zones mal couvertes (tout en haut de l'arbre) ──
        qa_name = low_coverage_layer_display_name(coverage_threshold_percent)
        for qa_path in (qa_paths or []):
            if not qa_path:
                continue
            qa_str = str(qa_path)
            cible = groupe_qualite(groupe_analyse(root, titre_analyse))
            existante = _reuse_existing(project, qa_name, qa_str, loaded_layers, combined_extent)
            if existante:
                _ranger(root, existante, cible, en_tete=True)
                logger.info(f"Couche QA déjà présente: {qa_name}")
                continue
            layer = build_low_coverage_vector_layer(qa_str, coverage_threshold_percent, logger)
            if layer is None:
                logger.warning(f"Impossible de charger la couche QA: {qa_str}")
                continue
            project.addMapLayer(layer, False)
            cible.insertLayer(0, layer)  # en tête de « Qualité de la donnée », au-dessus de la couverture
            loaded_layers.append(layer)
            combined_extent = _combine(combined_extent, layer.extent())
            loaded_count += 1
            logger.info(f"Couche QA chargée: {qa_name}")

        if titre_analyse:
            regler_indices(groupe_analyse(root, titre_analyse))

        if loaded_count > 0:
            from ..app.user_narrator import _human_count
            logger.log(
                USER_INFO,
                f"📂 {_human_count(loaded_count, 'couche ajoutée', 'couches ajoutées')} au projet QGIS",
            )

        if loaded_layers:
            _deferred_zoom(loaded_layers, project, logger)

    except Exception as e:  # noqa: BLE001
        logger.error(f"Erreur lors du chargement des couches: {e}")


# ── helpers ─────────────────────────────────────────────────────────


def _rvt_type_of(vrt) -> str:
    """Type de produit RVT depuis le chemin du VRT (ex. ``MNT``, ``LD_...``, ``HS_...``)."""
    vp = Path(str(vrt))
    return vp.parent.parent.name if vp.parent.name == "tif" else vp.parent.name


def _combine(extent, new_extent):
    if extent.isNull():
        return new_extent
    extent.combineExtentWith(new_extent)
    return extent


def _ensure_layer_crs(layer, logger, fallback_authid: Optional[str] = None) -> None:
    """Affecte le CRS du run si la couche n'en a pas d'exploitable.

    Un CRS local « unnamed » (ex. MNT que PDAL a émis sans georéférencement
    reconnu) est invalide ou dépourvu de code d'autorité (``authid`` vide) côté
    QGIS. On lui **affecte** le CRS du run (sans reprojeter — les coordonnées sont
    déjà correctes) : celui de la trace ``traitement.json`` du dossier de la couche
    (``finalize_service.crs_de_repli_pour``, règle 2026-10-31 : MNT étrangers), à
    défaut EPSG:2154 ; ce qui évite l'erreur « Pas de transformation disponible
    entre unnamed et … » au zoom final. Garde-fou défensif : la correction de fond
    se fait à la source (``mnt.py``, CRS du run posé par les modes existing_*).
    """
    try:
        from qgis.core import QgsCoordinateReferenceSystem

        crs = layer.crs()
        if crs.isValid() and crs.authid():
            return  # CRS exploitable (code d'autorité présent) → ne pas toucher
        if not fallback_authid:
            from ..app.services.finalize_service import crs_de_repli_pour
            fallback_authid = crs_de_repli_pour(layer.source())
        target = QgsCoordinateReferenceSystem(fallback_authid)
        if target.isValid():
            layer.setCrs(target)
            logger.warning(f"CRS absent/local sur « {layer.name()} » → affecté {fallback_authid}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Impossible de fixer le CRS de « {layer.name()} »: {e}")


def regler_indices(parent) -> None:
    """Le groupe « Indices » d'une analyse est exclusif (un indice affiché à la fois, 2026-11-18) : le LD
    coché, sinon le premier (``nom_analyse.indice_coche``). Jamais à la racine (analyses sans titre,
    rasters à plat). Partagé par le chargement en direct et ``qgs_writer``."""
    from qgis.core import QgsLayerTree

    if parent.customProperty(PROPRIETE) is None:
        return
    groupe = parent.findGroup(GROUPE_INDICES)
    if groupe is None or not groupe.children():
        return
    types = [_rvt_type_of(n.layer().source()) if QgsLayerTree.isLayer(n) and n.layer() is not None else ""
             for n in groupe.children()]
    groupe.setIsMutuallyExclusive(True, indice_coche(types))


def _ranger(root, couche, cible, en_tete: bool = False, decochee: bool = False) -> None:
    """Déplace le nœud d'une couche déjà chargée dans ``cible`` (une analyse chargée avant la version qui
    a créé ce groupe) ; rien s'il y est déjà (le choix de l'utilisateur reste). Jamais de doublon : le
    nœud d'origine est retiré. ``decochee`` : la couche arrive décochée, comme une couche neuve."""
    noeud = root.findLayer(couche.id())
    if noeud is None or noeud.parent() is cible:
        return
    copie = noeud.clone()
    if en_tete:
        cible.insertChildNode(0, copie)
    else:
        cible.addChildNode(copie)
    if decochee:
        copie.setItemVisibilityChecked(False)
    noeud.parent().removeChildNode(noeud)


def _reuse_existing(project, layer_name, source, loaded_layers, combined_extent):
    """Si une couche de même nom + source existe déjà, la réutilise et la rend (sinon ``None``).

    Défensif : on force une relecture du datasource (``reload``) avant réutilisation.
    Si le fichier (VRT régénéré, GPKG réécrit) a changé sur disque depuis son
    chargement initial, QGIS afficherait sinon la version en mémoire (périmée).
    Best-effort — la purge au lancement (``purge_output_dir_layers``) reste la
    parade principale ; ceci couvre une couche chargée par un autre chemin.
    """
    for existing in project.mapLayersByName(layer_name):
        # Même nom et même fichier : la couche QA est chargée en « chemin|layername=… » mais demandée par
        # son seul chemin — sans cette tolérance, elle se dupliquait à chaque rechargement (2026-11-18).
        if existing.source() == source or existing.source().split("|")[0] == str(source).split("|")[0]:
            try:
                existing.reload()
                existing.triggerRepaint()
            except Exception:  # noqa: BLE001 — relecture best-effort, jamais bloquante
                pass
            loaded_layers.append(existing)
            _combine(combined_extent, existing.extent())
            return existing
    return None


def _retirer_groupes_vides(project) -> None:
    """Les groupes que la purge vient de vider — celui de l'analyse, ses « Structures » (et
    sous-groupes) et « Indices », l'ancien « Structures » de la racine ; jamais un groupe de
    l'utilisateur, jamais un groupe encore peuplé — ne restent pas vides dans l'arbre (constat de
    recette 68.4, 2026-10-26). Règle pure : ``nom_analyse.retirer_groupes_vides``."""
    from qgis.core import QgsLayerTree

    retirer_groupes_vides(project.layerTreeRoot(), QgsLayerTree.isGroup)


def purge_output_dir_layers(output_dir, logger: logging.Logger) -> int:
    """Retire du projet QGIS les couches périmées d'un ``output_dir`` avant un re-run.

    À appeler sur le **thread principal, au lancement** du run : libère les datasets
    ``index_<produit>.vrt`` / GPKG encore détenus par QGIS depuis un run précédent dans le
    **même** dossier de sortie, AVANT que le worker ne régénère les VRT. Sans cela,
    QGIS réécrit sa version en mémoire (périmée) par-dessus le VRT fraîchement
    régénéré → les dalles ajoutées restent invisibles. Best-effort : toute erreur est
    loggée sans jamais bloquer le lancement. Retourne le nombre de couches retirées.

    La décision (quelles couches) est déléguée au helper pur testable
    ``app.services.layer_purge.select_layers_to_purge`` ; ici on ne fait que les
    appels QGIS (énumération + ``removeMapLayers``).
    """
    try:
        from qgis.core import QgsProject

        from ..app.services.layer_purge import select_layers_to_purge

        if not output_dir:
            return 0
        project = QgsProject.instance()
        sources = {lid: lyr.source() for lid, lyr in project.mapLayers().items()}
        to_remove = select_layers_to_purge(sources, str(output_dir))
        if to_remove:
            project.removeMapLayers(to_remove)  # libère chaque dataProvider/dataset
            _retirer_groupes_vides(project)
            logger.info(
                f"{len(to_remove)} couche(s) du traitement précédent retirée(s) "
                "avant régénération (même dossier de sortie)."
            )
        return len(to_remove)
    except Exception as e:  # noqa: BLE001 — purge best-effort, jamais bloquante
        logger.warning(f"Purge des couches périmées impossible: {e}")
        return 0


def detacher_couches_du_dossier(output_dir, logger: logging.Logger) -> list:
    """Au lancement d'un traitement, **détache** de leur fichier les couches du projet qui lisent le dossier de
    sortie, sans les retirer (demande de l'utilisateur, 2026-11-12 : lancer un traitement ne doit fermer aucune
    couche ouverte, qu'elle vienne d'un traitement ou qu'il l'ait ouverte lui-même). La couche reste dans
    l'arbre, à sa place, cochée ou non, avec son style ; elle est simplement indisponible le temps du calcul.

    Le détachement est nécessaire : QGIS garde ouverts le VRT et le GeoPackage d'une couche chargée, Windows
    verrouille alors le fichier et le traitement ne peut pas le réécrire (mesuré : ``PermissionError`` couche
    ouverte, fichier libre couche détachée, sous QGIS 3.44 et 4.0.3) ; et QGIS réécrirait son VRT périmé
    par-dessus le nouveau. Les couches visées sont celles de ``select_layers_to_purge`` (par chemin, jamais par
    nom). Rend ``[(id, source, nom, fournisseur), …]`` pour :func:`rattacher_couches`. Thread principal."""
    try:
        from qgis.core import QgsProject

        from ..app.services.layer_purge import select_layers_to_purge

        if not output_dir:
            return []
        project = QgsProject.instance()
        couches = project.mapLayers()
        detachees = []
        for lid in select_layers_to_purge({i: c.source() for i, c in couches.items()}, str(output_dir)):
            couche = couches[lid]
            detachees.append((lid, couche.source(), couche.name(), couche.providerType()))
            couche.setDataSource("", couche.name(), couche.providerType())      # libère le fichier, garde le style
        if detachees:
            logger.info(f"{len(detachees)} couche(s) du dossier de sortie mise(s) en attente le temps du "
                        "traitement ; elles seront rebranchées à la fin.")
        return detachees
    except Exception as e:  # noqa: BLE001 — jamais bloquant
        logger.warning(f"Mise en attente des couches du dossier de sortie impossible: {e}")
        return []


def rattacher_couches(detachees, logger: logging.Logger) -> tuple:
    """Rebranche à la fin du traitement (réussi, annulé ou en erreur) les couches de
    :func:`detacher_couches_du_dossier` sur leur fichier, relu à neuf. Une couche que l'utilisateur a retirée
    entre-temps est ignorée ; une couche dont le fichier n'existe plus (structure qui n'est plus produite) est
    retirée, et son groupe s'il reste vide. Rend ``(rebranchées, retirées)``. Thread principal."""
    try:
        import os

        from qgis.core import QgsProject

        from ..app.services.layer_purge import _strip_decoration

        project = QgsProject.instance()
        rebranchees, perdues = 0, []
        for lid, source, nom, fournisseur in detachees or []:
            couche = project.mapLayer(lid)
            if couche is None:
                continue
            if not os.path.exists(_strip_decoration(source)):
                perdues.append(lid)
                continue
            couche.setDataSource(source, nom, fournisseur)
            if couche.isValid():
                couche.triggerRepaint()
                rebranchees += 1
            else:
                perdues.append(lid)
        if perdues:
            project.removeMapLayers(perdues)
            _retirer_groupes_vides(project)
        if rebranchees or perdues:
            logger.info(f"{rebranchees} couche(s) rebranchée(s) sur le dossier de sortie"
                        + (f", {len(perdues)} retirée(s) (fichier disparu)." if perdues else "."))
        return rebranchees, len(perdues)
    except Exception as e:  # noqa: BLE001 — jamais bloquant
        logger.warning(f"Rebranchement des couches impossible: {e}")
        return 0, 0


def _deferred_zoom(loaded_layers, project, logger) -> None:
    """Zoom différé (QTimer 0) : le canvas n'a pas encore synchronisé son CRS
    dans le même tour de boucle que addMapLayer."""
    try:
        from qgis.PyQt.QtCore import QTimer
        from qgis.utils import iface

        if not (iface and iface.mapCanvas()):
            logger.info("iface indisponible — zoom non effectué")
            return
        layers_for_zoom = list(loaded_layers)

        def _do_zoom():
            try:
                from qgis.core import QgsCoordinateTransform, QgsRectangle
                canvas = iface.mapCanvas()
                canvas_crs = canvas.mapSettings().destinationCrs()
                combined = QgsRectangle()
                combined.setMinimal()
                for lay in layers_for_zoom:
                    ext = lay.extent()
                    if ext.isNull() or ext.isEmpty():
                        continue
                    l_crs = lay.crs()
                    if l_crs.isValid() and canvas_crs.isValid() and l_crs != canvas_crs:
                        try:
                            xf = QgsCoordinateTransform(l_crs, canvas_crs, project)
                            ext = xf.transformBoundingBox(ext)
                        except Exception:
                            continue
                    if not (ext.isNull() or ext.isEmpty()):
                        combined.combineExtentWith(ext)
                if not (combined.isNull() or combined.isEmpty()):
                    combined.scale(1.05)
                    canvas.setExtent(combined)
                    canvas.refresh()
                    logger.log(USER_INFO, "Zoom sur l'étendue des résultats")
                    return
                iface.setActiveLayer(layers_for_zoom[0])
                iface.zoomToActiveLayer()
                logger.log(USER_INFO, "Zoom sur l'étendue des résultats")
            except Exception as ze:  # noqa: BLE001
                logger.warning(f"Impossible de zoomer: {ze}")

        QTimer.singleShot(0, _do_zoom)
    except Exception as zoom_err:  # noqa: BLE001
        logger.warning(f"Impossible de programmer le zoom: {zoom_err}")
