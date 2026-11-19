"""Un enclos détecté est une emprise pleine, sans trou (2026-11-19).

Vu par l'utilisateur à Rambouillet (606331,97 ; 6843530,49) : la segmentation rendait l'enclos en anneau
(deux trous), 2 enclos sur 8 ; les emprises d'entraînement, elles, sont pleines. Les trous sont bouchés
au nettoyage final de la couche, ce qui couvre aussi ceux qu'ouvre la fusion de fragments.
"""
import inspect

from shapely.geometry import MultiPolygon, Polygon, box

import pipeline.cv.conversion_shp as cs


def test_les_trous_sont_bouches():
    anneau = Polygon(box(0, 0, 100, 100).exterior.coords, [box(10, 10, 40, 40).exterior.coords,
                                                           box(60, 60, 90, 90).exterior.coords])
    plein = cs.emprise_pleine(anneau)
    assert not plein.interiors and plein.area == 10000
    multi = cs.emprise_pleine(MultiPolygon([anneau, box(200, 0, 210, 10)]))
    assert all(not p.interiors for p in multi.geoms) and len(multi.geoms) == 2
    assert cs.emprise_pleine(box(0, 0, 1, 1)).equals(box(0, 0, 1, 1))


def test_seuls_les_enclos_sont_remplis():
    assert {"enclos", "enclos_circulaire"} <= cs.CLASSES_EMPRISE_PLEINE
    assert "parcellaire" not in cs.CLASSES_EMPRISE_PLEINE
    assert "emprise_pleine" in inspect.getsource(cs.create_shapefile_from_detections)
