# Plateforme de prévision de la demande et de rééquilibrage BIXI

🇬🇧 [English version](README.md)

Un projet de science des données bilingue (English / Français) sur le réseau de vélos en libre-service
BIXI de Montréal. Il répond à la question : **combien de départs et d’arrivées faut-il prévoir à
chaque station, et où faut-il redistribuer les vélos?**

> **État d’avancement :** étape 1 sur 10 terminée (structure du projet et squelette bilingue de
> l’application). Un résumé des résultats (modèle par rapport aux références, scénarios de
> rééquilibrage, lien vers la démo en ligne) sera ajouté ici après les étapes 6 à 9.

## Portée
- Déplacements historiques de 2023 à 2025, restreints à 50 stations après vérification de la
  qualité et de la continuité des données
- Analyse horaire des départs et des arrivées
- Prévisions de la demande sur 24 heures avec intervalles de prédiction, à partir de variables
  météo et de calendrier
- Carte interactive des stations
- Simulation de rééquilibrage selon des hypothèses explicites sur l’inventaire initial de vélos et
  la capacité des stations

**Limite importante :** les déplacements observés ne correspondent pas à la demande réelle. Les
déplacements historiques seuls ne permettent pas d’établir les ruptures de stock ni la demande
non satisfaite; les résultats du rééquilibrage sont donc des estimations de scénarios. Voir
[docs/decisions.md](docs/decisions.md) (en anglais).

## Feuille de route
| Étape | Livrable | État |
|---|---|---|
| 1 | Structure du projet et squelette bilingue de l’application | Terminée |
| 2 | Téléchargement, inspection et validation des données BIXI | Prochaine |
| 3 | Pipeline d’ingestion reproductible | |
| 4 | Exploration des tendances et cartes des stations | |
| 5 | Météo et tables de modélisation horaires | |
| 6 | Modèles de référence et évaluation des prévisions | |
| 7 | Stockage et diffusion des prévisions avec FastAPI | |
| 8 | Simulation de redistribution | |
| 9 | Tableau de bord bilingue complet | |
| 10 | Documentation, tests et déploiement | |

## Démarrage rapide
```bash
python -m venv .venv && source .venv/bin/activate
make install        # pip install -e ".[app,dev]"
make test
make app            # http://localhost:8501  (ajoutez ?lang=fr pour le français)
```
Ou avec Docker : `docker compose up --build`.

## Structure du projet
```
src/bixi/
  i18n.py            traduction et formatage selon la langue
  locales/           en.json, fr.json (tout le texte de l’interface)
  config.py          paramètres lus depuis les variables d’environnement
  app/               tableau de bord Streamlit (registre, état, vues)
tests/               tests de cohérence et de formatage i18n
docs/decisions.md    décisions de conception et protocole d’évaluation
```

## Prise en charge des langues
L’anglais est la langue par défaut; le sélecteur dans la barre latérale change la navigation, les
filtres, les libellés des graphiques, les infobulles, les explications et les messages d’erreur.
Les noms de stations restent dans leur forme originale. Les nombres, pourcentages et dates suivent
la langue choisie (conventions canadiennes). Pour ajouter du texte, ajoutez la même clé dans
`en.json` et `fr.json`; les tests échouent si les deux fichiers divergent.

## Conventions
Le code, les colonnes de base de données et les champs d’API sont en anglais. Les données
proviennent des données ouvertes de BIXI; vérifiez les conditions d’utilisation en vigueur et citez
la source avant de publier des résultats.
