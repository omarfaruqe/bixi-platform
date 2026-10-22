# Plateforme de prévision de la demande et de rééquilibrage BIXI

[![Live demo](https://img.shields.io/badge/live_demo-103.99.176.180%2Fbixi-2a78d6)](http://103.99.176.180/bixi/)
![Version](https://img.shields.io/badge/version-0.1.0-blue)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.40%2B-FF4B4B?logo=streamlit&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)
[![CI](https://github.com/omarfaruqe/bixi-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/omarfaruqe/bixi-platform/actions/workflows/ci.yml)

🇬🇧 [English version](README.md)

Un projet de science des données bilingue (English / Français) sur le réseau de vélos en libre-service
BIXI de Montréal. Il répond à la question : **combien de départs et d’arrivées faut-il prévoir à
chaque station, et où faut-il redistribuer les vélos?**

**Démo en ligne :** <http://103.99.176.180/bixi/?lang=fr> (anglais : <http://103.99.176.180/bixi/>),
un tableau de bord Streamlit servi avec Docker derrière Caddy.

> **État d’avancement :** étapes 1 à 9 sur 10 terminées : les sept pages du tableau de bord
> sont en ligne en anglais et en français. L’étape 10 (documentation, tests et finition du
> déploiement) est la prochaine.

## Principaux résultats
- **Les prévisions battent les références.** Sur une période de validation de six semaines
  (du 1er octobre au 14 novembre 2025, jamais vue à l’entraînement), LightGBM avec une fonction
  de perte de Poisson a une erreur absolue moyenne de 1,92 départ par station-heure : **33 % de
  moins** que « la même heure la semaine précédente » et 27 % de moins que la meilleure référence
  simple.
- **Les prévisions météo comptent, la météo parfaite à peine plus.** Les prévisions météo de la
  veille réduisent l’erreur de 7 à 8 % au total et d’environ un tiers les heures de pluie;
  connaître la météo réelle n’ajouterait que 0 à 3 %.
- **Des intervalles fiables.** Les intervalles de prédiction à 80 % (modèles de quantiles et
  calibration conforme) contiennent la valeur réelle 80 % du temps.
- **Le rééquilibrage fondé sur les prévisions est rentable.** Sur 45 jours, des tournées de camions
  optimisées avec OR-Tools à partir des prévisions de la veille réduisent de **20 %** les
  station-heures sans vélo ou sans point d’ancrage libre (2 camions, stations à moitié pleines au
  départ), contre 13 % pour une règle empirique, avec 15 % moins de kilomètres; c’est deux tiers de
  ce qu’une connaissance parfaite de la journée permettrait.
- **Le navettage crée le déséquilibre.** En semaine, le matin, le Plateau perd des vélos et le
  centre-ville se remplit : Square-Victoria gagne environ 125 vélos entre 7 h et 10 h, soit
  3,4 fois ses 37 points d’ancrage.

Détails : [docs/model_results.md](docs/model_results.md) et [docs/decisions.md](docs/decisions.md)
(en anglais).

## Portée
- Déplacements historiques de 2023 à 2025 (39 millions), restreints à 50 stations après
  vérification de la qualité et de la continuité des données
- Analyse horaire des départs et des arrivées, carte des stations
- Prévisions horaires émises la veille avec intervalles de prédiction à 80 %, à partir de la
  demande passée, du calendrier québécois, des événements et des prévisions météo archivées
  (aucune information future)
- Base de prévisions (PostgreSQL) et API en lecture seule (FastAPI)
- Simulation de rééquilibrage selon des hypothèses explicites sur l’inventaire initial de vélos et
  la capacité des stations

**Limite importante :** les déplacements observés ne correspondent pas à la demande réelle. Les
déplacements historiques seuls ne permettent pas d’établir les ruptures de stock ni la demande
non satisfaite; les résultats du rééquilibrage sont donc des estimations de scénarios.

## Feuille de route
| Étape | Livrable | État |
|---|---|---|
| 1 | Structure du projet et squelette bilingue de l’application | Terminée |
| 2 | Téléchargement, inspection et validation des données BIXI | Terminée |
| 3 | Pipeline d’ingestion reproductible | Terminée |
| 4 | Exploration des déplacements et carte des stations | Terminée |
| 5 | Météo et tables horaires de modélisation | Terminée |
| 6 | Modèles de référence et évaluation des prévisions | Terminée |
| 7 | Stockage et diffusion des prévisions avec FastAPI | Terminée |
| 8 | Simulation de redistribution | Terminée |
| 9 | Tableau de bord bilingue complet | Terminée |
| 10 | Documentation, tests, déploiement | Déployé tôt; finition à venir |

## Démarrage rapide
```bash
python -m venv .venv && source .venv/bin/activate
make install        # pip install -e ".[app,data,ml,api,dev]"
make test
make data           # stations, ingestion, variables (données brutes : python -m bixi.download all)
python -m bixi.models   # validations et modèles finaux (macOS : brew install libomp)
make app            # http://localhost:8501/?lang=fr
make api            # http://localhost:8000/docs  (nécessite DATABASE_URL)
```
Déploiement sur un serveur avec Docker : [deploy/README.md](deploy/README.md) (en anglais).

## Langues
L’anglais est la langue par défaut; le sélecteur de la barre latérale change la navigation, les
filtres, les libellés des graphiques, les infobulles, les explications et les messages d’erreur.
Les noms de stations restent dans leur forme originale. Les nombres, pourcentages et dates suivent
la langue choisie (paramètres régionaux canadiens).

## Données et conventions
Déplacements : [données ouvertes de BIXI Montréal](https://bixi.com/fr/donnees-ouvertes/).
Météo : [Open-Meteo](https://open-meteo.com/). Le code, les colonnes de la base de données et les
champs de l’API sont en anglais.
