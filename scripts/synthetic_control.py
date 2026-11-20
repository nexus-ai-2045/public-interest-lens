"""合成対照（SC-02、SC-03）。

重みは非負で合計 1（許容 1e-8）。予測変数の距離を最小にする。
効果は、処置後の実績と重みつき平均との差。
確かさは、国を入れ替えたプラセボの、事後と事前の RMSPE の比（SC-03）。
比べる国が J のとき p 値の下限は 1/(J+1)。J=12 のときは 1/13 で、0.05 を下回らない。

使ってよい条件は SC-04 の第5節（p.408）と第6節（p.413）。確かめ方は第7節（p.414）。
予測変数に、事前の結果の全年と共変量を同時に入れない（SC-06）。
罰則は SC-13。既定は 0。
国単位の先例は SC-22（Matti 2024, Economic Papers, doi 10.1111/1759-3441.12408）。

このモジュールは synthdid を依存にしない。依存として書くときは、配布元は GitHub であり、CRAN には無い。
拡張版（SC-12）は入れない。議員への配分はしない。公開データにはつながない。

解は scipy の二次計画に、有効制約の一次条件で仕上げたもの。指数で重みを更新する試作は使わない。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, minimize

WEIGHT_TOL = 1e-8
REPLICATION_NOT_RUN = (
    "バスクとカリフォルニアの再現実装はしていない。"
    "よく出回る系列は R の Synth に同梱され、ライセンスは GPL である。"
    "GPL のデータをこのリポジトリへ同梱できない。"
    "配布条件を確かめられた別のファイルが無いため、再現実装の数値は出していない。"
)

OWN_DEFAULTS = (
    {"id": "V-02", "name": "penalty", "value": 0.0, "label": "独自に決めた値。重みが一つに決まらないときの罰則は 0。"},
    {"id": "V-03", "name": "v_mode", "value": "identity", "label": "独自に決めた値。V は単位行列。"},
    {"id": "V-04", "name": "predictors", "value": "pre_outcome_all", "label": "独自に決めた値。予測変数は事前の結果を全年。感度は平均と共変量。"},
    {"id": "V-06", "name": "rmspe_pre_limit", "value": 1.0, "label": "独自に決めた値。事前 RMSPE の上限は 1。"},
    {"id": "V-07", "name": "exclude_codes", "value": (), "label": "独自に決めた値。常時の除外コードは空。キャッチアップを含めるかは引数。"},
    {"id": "V-08", "name": "placebo_mspe_multiple", "value": None, "label": "独自に決めた値。プラセボを倍率で除外しない。"},
    {"id": "V-09", "name": "inference", "value": "in_space_ratio", "label": "独自に決めた値。推論は in-space の RMSPE 比。p 値の線では隠さない。"},
    {"id": "V-11", "name": "min_pre_years", "value": 1, "label": "独自に決めた値。事前期間の最低は 1 年。"},
    {"id": "missing", "name": "missing", "value": "drop", "label": "独自に決めた値。欠損は落とす。"},
)


@dataclass(frozen=True)
class CountrySeries:
    code: str
    outcome: tuple[tuple[int, float], ...]
    covariates: tuple[tuple[str, tuple[tuple[int, float], ...]], ...] = ()
    catchup: bool = False
    income_ratio: float | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyCase:
    policy_id: str
    treated: str
    series: tuple[CountrySeries, ...]
    outcome_kind: str = "outcome"


@dataclass(frozen=True)
class SynthConfig:
    """t0_year は処置前の最後の年。それより後を処置後とする。include_catchup は引数で、既定を持たない。"""
    t0_year: int
    include_catchup: bool
    penalty: float = 0.0
    v_mode: str = "identity"
    predictors: str = "pre_outcome_all"
    rmspe_pre_limit: float = 1.0
    exclude_codes: tuple[str, ...] = ()
    catchup_ratio: float | None = None
    placebo_mspe_multiple: float | None = None
    inference: str = "in_space_ratio"
    p_value_line: float | None = None
    min_pre_years: int = 1
    missing: str = "drop"
    seed: int = 0
    weight_tol: float = WEIGHT_TOL
    hull_tol: float = WEIGHT_TOL
    in_time_shift: int = 1


@dataclass(frozen=True)
class Estimate:
    policy_id: str
    case_outcome_kind: str
    tau: tuple[tuple[int, float], ...] | None
    withheld_reasons: tuple[str, ...]
    weights: tuple[tuple[str, float], ...]
    rmspe_pre: float | None
    rmspe_post: float | None
    p_value: float | None
    p_value_denominator: int | None
    p_value_line: float | None
    p_floor_note: str
    ratios: tuple[tuple[str, float], ...]
    leave_one_out: tuple[tuple[str, tuple[tuple[int, float], ...] | None], ...]
    in_time: tuple[tuple[int, float], ...] | None
    certainty: str
    sign_disagreement: bool
    donor_pool: tuple[str, ...]
    dropped: tuple[tuple[str, str], ...]
    contemporaneous_notes: tuple[str, ...]
    covariate_balance: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class _Fit:
    weights: tuple[tuple[str, float], ...]
    tau: tuple[tuple[int, float], ...]
    rmspe_pre: float
    rmspe_post: float
    hull_distance: float
    balance: tuple[tuple[str, float], ...]


def _as_map(pairs) -> dict[int, float]:
    return {int(year): float(value) for year, value in pairs}


def _column(series: CountrySeries, years: list[int]) -> np.ndarray:
    values = _as_map(series.outcome)
    return np.array([values[year] for year in years], dtype=float)


def _predictor(series: CountrySeries, years: list[int], mode: str, cov_names: tuple[str, ...]) -> np.ndarray | None:
    outcome = _column(series, years)
    if mode == "pre_outcome_all":
        return outcome
    if mode == "mean_plus_covariates":
        parts = [np.array([float(outcome.mean())])]
        cov = {name: _as_map(values) for name, values in series.covariates}
        for name in cov_names:
            values = cov.get(name)
            if values is None or any(year not in values for year in years):
                return None
            parts.append(np.array([float(np.mean([values[year] for year in years]))]))
        return np.concatenate(parts)
    raise ValueError(mode)


def _other_mode(mode: str) -> str:
    if mode == "pre_outcome_all":
        return "mean_plus_covariates"
    if mode == "mean_plus_covariates":
        return "pre_outcome_all"
    raise ValueError(mode)


def _rmspe(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def _ratio(pre: float, post: float, tol: float) -> float:
    if pre <= tol and post <= tol:
        return 0.0
    if pre <= tol:
        return math.inf
    return post / pre


def _mspe(rmspe: float, tol: float) -> float:
    if rmspe <= tol:
        return 0.0
    return rmspe ** 2


def _solve_weights(x1: np.ndarray, x0: np.ndarray, penalty: float) -> np.ndarray:
    """非負・合計1の二次計画。有効制約の一次条件で、許容内に着くまで落とす。"""
    predictors = np.asarray(x0, dtype=float)
    target = np.asarray(x1, dtype=float)
    width = predictors.shape[1]
    if width == 1:
        return np.array([1.0])
    gaps = np.sum((predictors - target[:, None]) ** 2, axis=0)

    def objective(weights: np.ndarray) -> float:
        residual = target - predictors @ weights
        return float(residual @ residual + penalty * gaps @ weights)

    def gradient(weights: np.ndarray) -> np.ndarray:
        residual = target - predictors @ weights
        return -2.0 * predictors.T @ residual + penalty * gaps

    def hessian(weights: np.ndarray) -> np.ndarray:
        return 2.0 * (predictors.T @ predictors)

    start = np.full(width, 1.0 / width)
    result = minimize(
        objective,
        start,
        method="trust-constr",
        jac=gradient,
        hess=hessian,
        bounds=Bounds(0.0, 1.0),
        constraints=LinearConstraint(np.ones(width), 1.0, 1.0),
        options={"maxiter": 500, "gtol": 1e-14, "verbose": 0},
    )
    weights = np.clip(result.x, 0.0, None)
    total = float(weights.sum())
    weights = weights / total if total > 0.0 else start
    active = weights > 1e-6
    for _ in range(width + 2):
        chosen = np.flatnonzero(active)
        if len(chosen) == 0:
            break
        columns = predictors[:, chosen]
        count = len(chosen)
        system = np.zeros((count + 1, count + 1))
        system[:count, :count] = 2.0 * (columns.T @ columns)
        system[:count, count] = 1.0
        system[count, :count] = 1.0
        rhs = np.zeros(count + 1)
        rhs[:count] = 2.0 * (columns.T @ target) - penalty * gaps[chosen]
        rhs[count] = 1.0
        try:
            solution = np.linalg.solve(system, rhs)
        except np.linalg.LinAlgError:
            solution = np.linalg.lstsq(system, rhs, rcond=None)[0]
        free = solution[:count]
        if np.all(free >= -1e-8):
            polished = np.zeros(width)
            polished[chosen] = np.clip(free, 0.0, None)
            scale = float(polished.sum())
            weights = polished / scale if scale > 0.0 else weights
            break
        active[chosen[int(np.argmin(free))]] = False
    weights[weights < 1e-12] = 0.0
    weights[int(np.argmax(weights))] += 1.0 - float(weights.sum())
    if np.any(weights < -WEIGHT_TOL) or abs(float(weights.sum()) - 1.0) > WEIGHT_TOL:
        raise RuntimeError("重みが非負・合計1の許容に入らなかった")
    weights[weights < 0.0] = 0.0
    return weights


def _fit(treated: CountrySeries, donors: list[CountrySeries], pre_years: list[int], post_years: list[int], config: SynthConfig, mode: str) -> _Fit | None:
    cov_names = tuple(name for name, _values in treated.covariates)
    target = _predictor(treated, pre_years, mode, cov_names)
    if target is None:
        return None
    usable: list[CountrySeries] = []
    columns: list[np.ndarray] = []
    for donor in donors:
        column = _predictor(donor, pre_years, mode, cov_names)
        if column is None:
            continue
        usable.append(donor)
        columns.append(column)
    if not usable:
        return None
    matrix = np.column_stack(columns)
    solved = _solve_weights(target, matrix, config.penalty)
    pre_actual = _column(treated, pre_years)
    pre_donors = np.column_stack([_column(donor, pre_years) for donor in usable])
    pre_hat = pre_donors @ solved
    if post_years:
        post_actual = _column(treated, post_years)
        post_hat = np.column_stack([_column(donor, post_years) for donor in usable]) @ solved
        tau = tuple((year, float(gap)) for year, gap in zip(post_years, post_actual - post_hat))
        post_error = _rmspe(post_actual, post_hat)
    else:
        tau = ()
        post_error = math.nan
    balance = []
    cov_maps = [{name: _as_map(values) for name, values in donor.covariates} for donor in usable]
    treated_cov = {name: _as_map(values) for name, values in treated.covariates}
    for name in cov_names:
        if any(year not in treated_cov.get(name, {}) for year in pre_years):
            continue
        treated_mean = float(np.mean([treated_cov[name][year] for year in pre_years]))
        donor_means = []
        usable_weights = []
        for donor_cov, weight in zip(cov_maps, solved):
            values = donor_cov.get(name)
            if values is None or any(year not in values for year in pre_years):
                continue
            donor_means.append(float(np.mean([values[year] for year in pre_years])))
            usable_weights.append(float(weight))
        if donor_means and abs(sum(usable_weights) - 1.0) <= 1e-6:
            balance.append((name, treated_mean - float(np.dot(usable_weights, donor_means))))
    return _Fit(
        weights=tuple((donor.code, float(weight)) for donor, weight in zip(usable, solved)),
        tau=tau,
        rmspe_pre=_rmspe(pre_actual, pre_hat),
        rmspe_post=post_error,
        hull_distance=float(np.linalg.norm(target - matrix @ solved)),
        balance=tuple(balance),
    )


def _mean_gap(path: tuple[tuple[int, float], ...] | None) -> float | None:
    if not path:
        return None
    return float(np.mean([value for _year, value in path]))


def _certainty(primary: tuple[tuple[int, float], ...] | None, sensitivity: tuple[tuple[int, float], ...] | None) -> tuple[bool, str]:
    left = _mean_gap(primary)
    right = _mean_gap(sensitivity)
    if left is None or right is None:
        return False, "比較できない"
    if abs(left) <= WEIGHT_TOL or abs(right) <= WEIGHT_TOL:
        return False, "ゼロを含む"
    if left * right < 0.0:
        return True, "低"
    return False, "符号は同じ"


def _select_donors(case: PolicyCase, config: SynthConfig) -> tuple[CountrySeries, list[CountrySeries], list[tuple[str, str]], list[int]]:
    by_code = {series.code: series for series in case.series}
    treated = by_code[case.treated]
    years = [year for year, _value in treated.outcome]
    needed = set(years)
    dropped: list[tuple[str, str]] = []
    donors: list[CountrySeries] = []
    for series in case.series:
        if series.code == treated.code:
            continue
        if series.code in config.exclude_codes:
            dropped.append((series.code, "除外コード"))
            continue
        if series.catchup and not config.include_catchup:
            dropped.append((series.code, "キャッチアップ国を含めない"))
            continue
        if (
            config.catchup_ratio is not None
            and not config.include_catchup
            and series.income_ratio is not None
            and series.income_ratio < config.catchup_ratio
        ):
            dropped.append((series.code, "所得比がしきい値未満"))
            continue
        if config.missing == "drop" and any(year not in _as_map(series.outcome) for year in needed):
            dropped.append((series.code, "欠損"))
            continue
        donors.append(series)
    return treated, donors, dropped, years


def _floor_note(donor_count: int) -> str:
    return (
        f"比べる国が {donor_count} のとき、p 値の下限は 1/{donor_count + 1} である。"
        "J=12 のときは 1/13 で、0.05 を下回らない。"
    )


def estimate(case: PolicyCase, config: SynthConfig) -> Estimate:
    np.random.seed(config.seed)
    if config.inference != "in_space_ratio":
        raise ValueError(config.inference)
    if config.v_mode != "identity":
        raise ValueError(config.v_mode)
    if config.missing != "drop":
        raise ValueError("欠損は落とす。0では埋めない")
    treated, donors, dropped, years = _select_donors(case, config)
    pre_years = [year for year in years if year <= config.t0_year]
    post_years = [year for year in years if year > config.t0_year]
    reasons: list[str] = []
    if not donors:
        reasons.append("比べる国が無い")
    if len(pre_years) < config.min_pre_years:
        reasons.append("事前期間が短い")
    if not post_years:
        reasons.append("処置後の年が無い")

    fit = _fit(treated, donors, pre_years, post_years, config, config.predictors) if donors and pre_years else None
    sensitivity = _fit(treated, donors, pre_years, post_years, config, _other_mode(config.predictors)) if donors and pre_years else None
    if fit is not None:
        if fit.hull_distance > config.hull_tol:
            reasons.append("比べる国の凸包の外")
        if fit.rmspe_pre > config.rmspe_pre_limit:
            reasons.append("事前の当てはまりが悪い")
    weights = fit.weights if fit is not None else ()
    disagree, certainty = _certainty(fit.tau if fit is not None else None, sensitivity.tau if sensitivity is not None else None)

    ratios: list[tuple[str, float]] = []
    p_value = None
    denominator = None
    if fit is not None and post_years and donors:
        ratios.append((treated.code, _ratio(fit.rmspe_pre, fit.rmspe_post, config.weight_tol)))
        kept = [ratios[0]]
        japan_mspe = _mspe(fit.rmspe_pre, config.weight_tol)
        pool = [treated, *donors]
        for donor in donors:
            others = [unit for unit in pool if unit.code != donor.code]
            placebo = _fit(donor, others, pre_years, post_years, config, config.predictors)
            if placebo is None:
                ratios.append((donor.code, math.inf))
                continue
            value = _ratio(placebo.rmspe_pre, placebo.rmspe_post, config.weight_tol)
            ratios.append((donor.code, value))
            if config.placebo_mspe_multiple is not None and _mspe(placebo.rmspe_pre, config.weight_tol) > config.placebo_mspe_multiple * japan_mspe:
                continue
            kept.append((donor.code, value))
        treated_ratio = ratios[0][1]
        no_smaller = sum(1 for _code, value in kept if value >= treated_ratio)
        denominator = len(kept)
        p_value = no_smaller / denominator if denominator else None

    leave_one_out = []
    if fit is not None and post_years:
        for code, weight in weights:
            if weight <= config.weight_tol:
                continue
            others = [donor for donor in donors if donor.code != code]
            refit = _fit(treated, others, pre_years, post_years, config, config.predictors) if others else None
            leave_one_out.append((code, None if refit is None else refit.tau))

    fake_t0 = config.t0_year - config.in_time_shift
    fake_pre = [year for year in years if year <= fake_t0]
    fake_post = [year for year in years if fake_t0 < year <= config.t0_year]
    in_time = None
    if donors and len(fake_pre) >= config.min_pre_years and fake_post:
        shifted = _fit(treated, donors, fake_pre, fake_post, config, config.predictors)
        if shifted is not None:
            in_time = shifted.tau
    if in_time is None:
        reasons.append("時点をずらしたプラセボが計算できない")

    tau = None
    if not reasons and fit is not None and p_value is not None and leave_one_out and in_time is not None:
        tau = fit.tau
    elif fit is not None and not any(reason != "時点をずらしたプラセボが計算できない" for reason in reasons):
        reasons.append("点推定だけでは出さない")

    return Estimate(
        policy_id=case.policy_id,
        case_outcome_kind=case.outcome_kind,
        tau=tau,
        withheld_reasons=tuple(reasons),
        weights=weights,
        rmspe_pre=None if fit is None else fit.rmspe_pre,
        rmspe_post=None if fit is None else fit.rmspe_post,
        p_value=p_value,
        p_value_denominator=denominator,
        p_value_line=config.p_value_line,
        p_floor_note=_floor_note(len(donors)),
        ratios=tuple(ratios),
        leave_one_out=tuple(leave_one_out),
        in_time=in_time,
        certainty=certainty,
        sign_disagreement=disagree,
        donor_pool=tuple(donor.code for donor in donors),
        dropped=tuple(dropped),
        contemporaneous_notes=tuple(treated.notes),
        covariate_balance=() if fit is None else fit.balance,
    )


def _json_value(value):
    if isinstance(value, float):
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        if math.isnan(value):
            return None
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def to_jsonable(estimate: Estimate) -> dict:
    payload = {
        "policy_id": estimate.policy_id,
        "outcome_kind": estimate.case_outcome_kind,
        "tau": estimate.tau,
        "withheld_reasons": estimate.withheld_reasons,
        "weights": estimate.weights,
        "rmspe_pre": estimate.rmspe_pre,
        "rmspe_post": estimate.rmspe_post,
        "p_value": estimate.p_value,
        "p_value_denominator": estimate.p_value_denominator,
        "p_value_line": estimate.p_value_line,
        "p_floor_note": estimate.p_floor_note,
        "ratios": estimate.ratios,
        "leave_one_out": estimate.leave_one_out,
        "in_time": estimate.in_time,
        "certainty": estimate.certainty,
        "sign_disagreement": estimate.sign_disagreement,
        "donor_pool": estimate.donor_pool,
        "dropped": estimate.dropped,
        "contemporaneous_notes": estimate.contemporaneous_notes,
        "covariate_balance": estimate.covariate_balance,
        "own_defaults": OWN_DEFAULTS,
    }
    return _json_value(payload)
