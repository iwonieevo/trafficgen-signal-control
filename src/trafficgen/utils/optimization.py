"""Generic solvers used by the traffic generator."""

import numpy as np
from scipy.optimize import nnls

MAX_CONDITION_NUMBER_FOR_EXACT_SOLVE = 1e10


def non_negative_least_squares_per_row(
    matrix: np.ndarray, targets: np.ndarray, target_weights: np.ndarray
) -> np.ndarray:
    """Per row of ``targets``: ``x >= 0`` minimising ``|weights * (matrix @ x - target)|``."""
    solutions = _exact_non_negative_solutions(matrix, targets)
    for row in np.flatnonzero(np.isnan(solutions).any(axis=1)):
        weights = target_weights[row]
        solutions[row], _ = nnls(matrix * weights[:, None], targets[row] * weights)
    return solutions


def _exact_non_negative_solutions(matrix: np.ndarray, targets: np.ndarray) -> np.ndarray:
    solutions = np.full((len(targets), matrix.shape[1]), np.nan)
    is_square = matrix.shape[0] == matrix.shape[1]
    if not is_square or np.linalg.cond(matrix) >= MAX_CONDITION_NUMBER_FOR_EXACT_SOLVE:
        return solutions
    exact = np.linalg.solve(matrix, targets.T).T
    is_non_negative = (exact >= 0).all(axis=1)
    solutions[is_non_negative] = exact[is_non_negative]
    return solutions
