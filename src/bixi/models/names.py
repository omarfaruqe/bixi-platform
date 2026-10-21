"""Model names shared by training and the dashboard. Import-light on purpose: the dashboard image
does not install LightGBM or SciPy, so nothing here may import them."""

MAIN = "lgbm_poisson"
INTERVAL = (0.1, 0.9)  # 80% prediction interval
