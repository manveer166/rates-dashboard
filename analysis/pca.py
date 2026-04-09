"""
PCA decomposition of the yield curve.

PC1 ≈ Level  (parallel shift — most variance ~80-90%)
PC2 ≈ Slope  (steepening / flattening)
PC3 ≈ Curvature (butterfly)
"""

import pandas as pd
import numpy as np
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from config import TENOR_LABELS


def run_pca(df: pd.DataFrame, n_components: int = 3) -> dict:
    """
    Run PCA on the yield curve.

    Parameters
    ----------
    df           : Master DataFrame (must contain TENOR_LABELS columns)
    n_components : Number of principal components to extract

    Returns
    -------
    dict with keys:
        loadings          – DataFrame (n_tenors × n_components)
        explained_variance – array of explained variance ratios
        scores            – DataFrame of factor scores over time
        cumulative_variance – cumulative explained variance
    """
    available = [c for c in TENOR_LABELS if c in df.columns]
    if len(available) < n_components + 1:
        return {}

    clean = df[available].dropna()
    if len(clean) < 30:
        return {}

    scaler = StandardScaler()
    scaled = scaler.fit_transform(clean)

    pca = PCA(n_components=n_components)
    scores_arr = pca.fit_transform(scaled)

    pc_names = []
    for i in range(n_components):
        label = ["Level", "Slope", "Curvature"]
        name  = label[i] if i < len(label) else f"PC{i+1}"
        pc_names.append(f"PC{i+1} ({name})")

    loadings = pd.DataFrame(
        pca.components_.T,
        index=available,
        columns=pc_names,
    )
    scores = pd.DataFrame(
        scores_arr,
        index=clean.index,
        columns=pc_names,
    )

    return {
        "loadings":             loadings,
        "explained_variance":   pca.explained_variance_ratio_,
        "cumulative_variance":  np.cumsum(pca.explained_variance_ratio_),
        "scores":               scores,
        "n_components":         n_components,
        "tenors":               available,
    }


def pca_summary_table(pca_result: dict) -> pd.DataFrame:
    """Human-readable variance explained table."""
    ev  = pca_result["explained_variance"]
    cum = pca_result["cumulative_variance"]
    rows = []
    for i, (e, c) in enumerate(zip(ev, cum)):
        rows.append({
            "Component":          pca_result["scores"].columns[i],
            "Explained Variance": f"{e:.1%}",
            "Cumulative":         f"{c:.1%}",
        })
    return pd.DataFrame(rows)
